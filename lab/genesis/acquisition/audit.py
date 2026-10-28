"""Durable, campaign-scoped one-shot AUDIT consumption for M7-G2.

The registry is an evaluator-side access control primitive.  It does not
replace M6 evidence, CAS, or the historical ledger: it merely makes the sole
AUDIT observation for a confirmatory campaign durable and non-adaptive.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep
from typing import Callable, Mapping

from lab.genesis.acquisition.benchmark import DatasetSplit, SplitEvaluation, TaskBenchmarkBinding
from lab.genesis.acquisition.confirmation import GEIAcceptancePolicy
from lab.genesis.acquisition.contracts import AcquisitionCampaignManifest, CandidateCommitment
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256
from lab.genesis.evidence.artifacts import is_artifact_hash


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


@dataclass(frozen=True, slots=True)
class AuditSlot:
    """The sole AUDIT slot for one policy-bound campaign/task observation."""

    policy_hash: str
    campaign_hash: str
    task_benchmark_binding_hash: str
    audit_split_commitment_hash: str
    slot_id: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.policy_hash,
            self.campaign_hash,
            self.task_benchmark_binding_hash,
            self.audit_split_commitment_hash,
        ):
            _require_hash(value, "genesis_durable_audit_slot_hash_invalid")
        object.__setattr__(self, "slot_id", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "policy_hash": self.policy_hash,
            "campaign_hash": self.campaign_hash,
            "task_benchmark_binding_hash": self.task_benchmark_binding_hash,
            "audit_split_commitment_hash": self.audit_split_commitment_hash,
        }

    def validate(self) -> bool:
        return self.slot_id == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class AuditClaimReceipt:
    """The immutable first candidate claim for an :class:`AuditSlot`."""

    schema_version: str
    slot: AuditSlot
    candidate_commitment_hash: str
    status: str
    claim_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.slot.validate():
            raise ValueError("genesis_durable_audit_claim_invalid")
        _require_hash(self.candidate_commitment_hash, "genesis_durable_audit_claim_candidate_invalid")
        if self.status not in {"CLAIMED", "COMPLETED"}:
            raise ValueError("genesis_durable_audit_claim_status_invalid")
        object.__setattr__(self, "claim_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "slot": self.slot.canonical_payload(),
            "candidate_commitment_hash": self.candidate_commitment_hash,
            "status": self.status,
        }

    def validate(self) -> bool:
        return self.claim_hash == canonical_sha256(self.canonical_payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AuditClaimReceipt":
        values = dict(payload)
        values["slot"] = AuditSlot(**dict(values["slot"]))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class AuditEvaluationReceipt:
    """The sealed, evaluator-side AUDIT result released after durable write."""

    schema_version: str
    claim_hash: str
    candidate_commitment_hash: str
    evaluation: SplitEvaluation
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.evaluation or self.evaluation.split is not DatasetSplit.AUDIT:
            raise ValueError("genesis_durable_audit_evaluation_invalid")
        _require_hash(self.claim_hash, "genesis_durable_audit_evaluation_claim_invalid")
        _require_hash(self.candidate_commitment_hash, "genesis_durable_audit_evaluation_candidate_invalid")
        if self.evaluation.candidate_skill_hash == "":
            raise ValueError("genesis_durable_audit_evaluation_skill_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "claim_hash": self.claim_hash,
            "candidate_commitment_hash": self.candidate_commitment_hash,
            "evaluation": self.evaluation.canonical_payload(),
        }

    def validate(self) -> bool:
        return self.receipt_hash == canonical_sha256(self.canonical_payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AuditEvaluationReceipt":
        values = dict(payload)
        values["evaluation"] = SplitEvaluation.from_payload(dict(values["evaluation"]))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class DurableAuditResult:
    slot: AuditSlot
    claim: AuditClaimReceipt
    evaluation: AuditEvaluationReceipt

    @property
    def audit(self) -> SplitEvaluation:
        return self.evaluation.evaluation

    def canonical_payload(self) -> dict[str, object]:
        return {
            "slot": self.slot.canonical_payload(),
            "claim": self.claim.canonical_payload(),
            "evaluation": self.evaluation.canonical_payload(),
        }

    def validate(self) -> bool:
        return (
            self.slot.validate()
            and self.claim.validate()
            and self.evaluation.validate()
            and self.claim.slot == self.slot
            and self.evaluation.claim_hash == self.claim.claim_hash
            and self.evaluation.candidate_commitment_hash
            == self.claim.candidate_commitment_hash
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "DurableAuditResult":
        return cls(
            AuditSlot(**dict(payload["slot"])),
            AuditClaimReceipt.from_payload(dict(payload["claim"])),
            AuditEvaluationReceipt.from_payload(dict(payload["evaluation"])),
        )


class DurableAuditClaimRegistry:
    """Filesystem-backed atomic write-once claims at evaluator trust boundary.

    ``O_EXCL`` is used for both the candidate claim and temporary execution
    lease. A retry with the same candidate returns its sealed receipt; a
    different candidate is rejected before the evaluator is called.
    """

    def __init__(self, root: str | Path, *, policy: GEIAcceptancePolicy) -> None:
        if not policy.validate():
            raise ValueError("genesis_durable_audit_policy_invalid")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy = policy

    def _path(self, slot: AuditSlot, suffix: str) -> Path:
        return self.root / f"{slot.slot_id}.{suffix}.json"

    @staticmethod
    def _write_once(path: Path, payload: Mapping[str, object]) -> bool:
        """Publish a durable record without ever exposing a partial final file.

        ``O_EXCL`` on the final name is insufficient: it makes an empty final
        inode observable between ``open`` and ``write``.  A concurrent reader
        can then mistake a legitimate in-flight result for corruption.  Write
        and fsync a private sibling first, then atomically hard-link it to the
        final name.  ``link`` has create-only semantics, unlike ``replace``,
        so it preserves the write-once audit invariant.
        """

        data = canonical_json_bytes(payload)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.pending")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                return False
            try:
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            except OSError:
                directory = None
            if directory is not None:
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            return True
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _read(path: Path) -> Mapping[str, object]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as error:
            raise ValueError("genesis_durable_audit_record_invalid") from error

    def _slot(
        self,
        *,
        campaign: AcquisitionCampaignManifest,
        task_binding: TaskBenchmarkBinding,
    ) -> AuditSlot:
        if (
            campaign.evidence_classification != "CONFIRMATORY_GE_I_EVIDENCE"
            or campaign.gei_acceptance_policy_hash != self.policy.policy_hash
            or not task_binding.validate()
            or task_binding.campaign_hash != campaign.campaign_hash
        ):
            raise ValueError("genesis_durable_audit_confirmatory_binding_invalid")
        return AuditSlot(
            self.policy.policy_hash,
            campaign.campaign_hash,
            task_binding.binding_hash,
            task_binding.split_commitment_hashes[DatasetSplit.AUDIT.value],
        )

    def _load_completed(
        self, slot: AuditSlot, candidate_commitment_hash: str
    ) -> DurableAuditResult | None:
        claim_path = self._path(slot, "claim")
        result_path = self._path(slot, "result")
        if not claim_path.exists():
            return None
        claim = AuditClaimReceipt.from_payload(self._read(claim_path))
        if not claim.validate() or claim.slot != slot:
            raise ValueError("genesis_durable_audit_claim_tampered")
        if claim.candidate_commitment_hash != candidate_commitment_hash:
            raise ValueError("genesis_durable_audit_candidate_conflict")
        if not result_path.exists():
            if claim.status == "COMPLETED":
                raise ValueError("genesis_durable_audit_completed_without_result")
            return None
        evaluation = AuditEvaluationReceipt.from_payload(self._read(result_path))
        if (
            not evaluation.validate()
            or evaluation.claim_hash != claim.claim_hash
            or evaluation.candidate_commitment_hash != candidate_commitment_hash
        ):
            raise ValueError("genesis_durable_audit_evaluation_tampered")
        return DurableAuditResult(slot, claim, evaluation)

    def evaluate(
        self,
        *,
        campaign: AcquisitionCampaignManifest,
        task_binding: TaskBenchmarkBinding,
        commitment: CandidateCommitment,
        evaluate_once: Callable[[], SplitEvaluation],
        wait_seconds: float = 10.0,
    ) -> DurableAuditResult:
        """Claim, evaluate, and persist exactly one AUDIT result.

        The callback is invoked only by the process which obtained the atomic
        lease. Its result is never returned until the immutable receipt exists.
        """

        slot = self._slot(campaign=campaign, task_binding=task_binding)
        if (
            not commitment.validate()
            or commitment.campaign_hash != campaign.campaign_hash
        ):
            raise ValueError("genesis_durable_audit_commitment_invalid")
        candidate_hash = commitment.commitment_hash
        claim_path = self._path(slot, "claim")
        proposed = AuditClaimReceipt(
            "genesis-m7-durable-audit-claim-v1", slot, candidate_hash, "CLAIMED"
        )
        if self._write_once(claim_path, proposed.canonical_payload()):
            claim = proposed
        else:
            existing = self._load_completed(slot, candidate_hash)
            if existing is not None:
                return existing
            claim = AuditClaimReceipt.from_payload(self._read(claim_path))
            if not claim.validate() or claim.slot != slot or claim.candidate_commitment_hash != candidate_hash:
                raise ValueError("genesis_durable_audit_claim_tampered")

        result_path = self._path(slot, "result")
        lease_path = self._path(slot, "lease")
        deadline = monotonic() + wait_seconds
        while True:
            completed = self._load_completed(slot, candidate_hash)
            if completed is not None:
                return completed
            if self._write_once(lease_path, {"slot_id": slot.slot_id, "claim_hash": claim.claim_hash}):
                break
            if monotonic() >= deadline:
                raise TimeoutError("genesis_durable_audit_evaluation_pending")
            sleep(0.005)

        try:
            audit = evaluate_once()
            if (
                not isinstance(audit, SplitEvaluation)
                or audit.split is not DatasetSplit.AUDIT
                or audit.candidate_skill_hash != commitment.candidate_skill_hash
            ):
                raise ValueError("genesis_durable_audit_callback_invalid")
            receipt = AuditEvaluationReceipt(
                "genesis-m7-durable-audit-evaluation-v1", claim.claim_hash,
                candidate_hash, audit,
            )
            if not self._write_once(result_path, receipt.canonical_payload()):
                completed = self._load_completed(slot, candidate_hash)
                if completed is None:
                    raise ValueError("genesis_durable_audit_result_race_invalid")
                return completed
            return DurableAuditResult(slot, claim, receipt)
        finally:
            try:
                lease_path.unlink()
            except FileNotFoundError:
                pass
