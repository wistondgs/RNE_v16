"""M7-H3A0-E: V3-native execution identity and battery closure contracts.

This module intentionally does *not* adapt a V2 campaign receipt.  It is the
authoritative V3 control-plane vocabulary that the sealed runner will use;
rank-canonical search and other lower-level engines remain versioned
dependencies, never the identity of a V3 campaign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from lab.genesis.acquisition.benchmark import DatasetSplit, SplitEvaluation
from lab.genesis.acquisition.v3_preregistration import (
    GEIConfirmatoryPredeclarationV3,
    V3CampaignBinding,
    V3ExecutionLaunchReceipt,
)
from lab.genesis.contracts.serialization import canonical_sha256


_CANONICAL_TASKS = (
    "abs_affine-0", "abs_affine-1", "affine-0", "affine-1",
    "quadratic_simple-0", "quadratic_simple-1",
)


def _hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
        raise ValueError(reason)


class V3CampaignTerminalStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"


class V3BatteryStatus(str, Enum):
    GE_I_BATTERY_SUPPORTED = "GE_I_BATTERY_SUPPORTED"
    GE_I_BATTERY_FAIL = "GE_I_BATTERY_FAIL"
    GE_I_BATTERY_NOT_PROVEN = "GE_I_BATTERY_NOT_PROVEN"


@dataclass(frozen=True, slots=True)
class V3ConfirmatoryCampaignManifest:
    """One campaign identity derived only from one V3 predeclaration."""

    schema_version: str
    predeclaration_hash: str
    battery_manifest_hash: str
    campaign_binding_hash: str
    campaign_id: str
    task_id: str
    g0_snapshot_hash: str
    baseline_manifest_hash: str
    split_commitment_hashes: Mapping[str, str]
    split_seed_commitment_hashes: Mapping[str, str]
    search_semantics_id: str
    search_implementation_hash: str
    frontier_policy_hash: str
    acceptance_policy_hash: str
    resource_policy_hash: str
    execution_source_manifest_hash: str
    environment_manifest_hash: str
    recovery_policy_hash: str
    campaign_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != "genesis-m7-v3-confirmatory-campaign-h3a0"
            or self.task_id not in _CANONICAL_TASKS
            or self.campaign_id != f"m7h3-confirmatory-{self.task_id}"
            or self.search_semantics_id != "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2"
        ):
            raise ValueError("genesis_h3_v3_campaign_identity_invalid")
        commitments = {str(key): str(value) for key, value in self.split_commitment_hashes.items()}
        seeds = {str(key): str(value) for key, value in self.split_seed_commitment_hashes.items()}
        if set(commitments) != {"TRAIN", "AUDIT", "HIDDEN", "TRANSFER"} or set(seeds) != set(commitments):
            raise ValueError("genesis_h3_v3_campaign_splits_invalid")
        for value in (
            self.predeclaration_hash, self.battery_manifest_hash, self.campaign_binding_hash,
            self.g0_snapshot_hash, self.baseline_manifest_hash, *commitments.values(), *seeds.values(),
            self.search_implementation_hash, self.frontier_policy_hash, self.acceptance_policy_hash,
            self.resource_policy_hash, self.execution_source_manifest_hash,
            self.environment_manifest_hash, self.recovery_policy_hash,
        ):
            _hash(value, "genesis_h3_v3_campaign_hash_invalid")
        object.__setattr__(self, "split_commitment_hashes", dict(sorted(commitments.items())))
        object.__setattr__(self, "split_seed_commitment_hashes", dict(sorted(seeds.items())))
        object.__setattr__(self, "campaign_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "predeclaration_hash": self.predeclaration_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "campaign_binding_hash": self.campaign_binding_hash,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "g0_snapshot_hash": self.g0_snapshot_hash,
            "baseline_manifest_hash": self.baseline_manifest_hash,
            "split_commitment_hashes": self.split_commitment_hashes,
            "split_seed_commitment_hashes": self.split_seed_commitment_hashes,
            "search_semantics_id": self.search_semantics_id,
            "search_implementation_hash": self.search_implementation_hash,
            "frontier_policy_hash": self.frontier_policy_hash,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "resource_policy_hash": self.resource_policy_hash,
            "execution_source_manifest_hash": self.execution_source_manifest_hash,
            "environment_manifest_hash": self.environment_manifest_hash,
            "recovery_policy_hash": self.recovery_policy_hash,
        }


def derive_v3_confirmatory_campaign(
    *, predeclaration: GEIConfirmatoryPredeclarationV3, campaign_id: str,
) -> V3ConfirmatoryCampaignManifest:
    """Derive a campaign manifest; no caller-selected scientific field exists."""

    if not predeclaration.validate():
        raise ValueError("genesis_h3_v3_campaign_predeclaration_invalid")
    binding: V3CampaignBinding | None = next(
        (item for item in predeclaration.battery.campaign_bindings if item.campaign_id == campaign_id), None,
    )
    if binding is None:
        raise ValueError("genesis_h3_v3_campaign_not_authorized")
    battery = predeclaration.battery
    return V3ConfirmatoryCampaignManifest(
        "genesis-m7-v3-confirmatory-campaign-h3a0", predeclaration.predeclaration_hash,
        battery.battery_manifest_hash, binding.binding_hash, binding.campaign_id, binding.task_id,
        binding.g0_snapshot_hash, binding.baseline_manifest_hash,
        binding.split_commitment_hashes, binding.split_seed_commitment_hashes,
        battery.search_semantics_id, battery.search_implementation_hash,
        battery.frontier_policy_hash, battery.acceptance_policy_hash, battery.resource_policy_hash,
        predeclaration.execution_source.manifest_hash, predeclaration.environment.manifest_hash,
        predeclaration.recovery_policy.policy_hash,
    )


@dataclass(frozen=True, slots=True)
class V3CandidateCommitment:
    """Pre-AUDIT candidate binding owned by the V3 campaign control plane."""

    schema_version: str
    campaign_hash: str
    candidate_skill_hash: str
    candidate_program_hash: str
    training_commitment_hash: str
    search_receipt_hash: str
    ranking_evidence_hash: str
    completed_level: int
    commitment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != "genesis-m7-v3-candidate-commitment-h3a0"
            or not isinstance(self.completed_level, int)
            or isinstance(self.completed_level, bool)
            or self.completed_level < 1
        ):
            raise ValueError("genesis_h3_v3_candidate_commitment_invalid")
        for value in (
            self.campaign_hash, self.candidate_skill_hash, self.candidate_program_hash,
            self.training_commitment_hash, self.search_receipt_hash, self.ranking_evidence_hash,
        ):
            _hash(value, "genesis_h3_v3_candidate_commitment_hash_invalid")
        object.__setattr__(self, "commitment_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_hash": self.campaign_hash,
            "candidate_skill_hash": self.candidate_skill_hash,
            "candidate_program_hash": self.candidate_program_hash,
            "training_commitment_hash": self.training_commitment_hash,
            "search_receipt_hash": self.search_receipt_hash,
            "ranking_evidence_hash": self.ranking_evidence_hash,
            "completed_level": self.completed_level,
        }


@dataclass(frozen=True, slots=True)
class V3AuditSlot:
    """The sole AUDIT observation, keyed by V3 rather than H2 identity."""

    predeclaration_hash: str
    battery_manifest_hash: str
    campaign_hash: str
    acceptance_policy_hash: str
    audit_split_commitment_hash: str
    slot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.predeclaration_hash, self.battery_manifest_hash, self.campaign_hash,
            self.acceptance_policy_hash, self.audit_split_commitment_hash,
        ):
            _hash(value, "genesis_h3_v3_audit_slot_hash_invalid")
        object.__setattr__(self, "slot_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "predeclaration_hash": self.predeclaration_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "campaign_hash": self.campaign_hash,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "audit_split_commitment_hash": self.audit_split_commitment_hash,
        }


@dataclass(frozen=True, slots=True)
class V3DurableAuditReceipt:
    schema_version: str
    slot: V3AuditSlot
    candidate_commitment_hash: str
    evaluation: SplitEvaluation
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != "genesis-m7-v3-durable-audit-receipt-h3a0" or self.evaluation.split is not DatasetSplit.AUDIT:
            raise ValueError("genesis_h3_v3_audit_receipt_invalid")
        _hash(self.candidate_commitment_hash, "genesis_h3_v3_audit_candidate_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "slot": self.slot.canonical_payload(),
            "candidate_commitment_hash": self.candidate_commitment_hash,
            "evaluation": self.evaluation.canonical_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "V3DurableAuditReceipt":
        values = dict(payload)
        values["slot"] = V3AuditSlot(**values["slot"])
        values["evaluation"] = SplitEvaluation.from_payload(values["evaluation"])
        return cls(**values)


class V3DurableAuditRegistry:
    """V3 one-shot AUDIT backend with same-candidate idempotence only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def evaluate(self, *, slot: V3AuditSlot, commitment: V3CandidateCommitment,
                 evaluate_once: Callable[[], SplitEvaluation]) -> V3DurableAuditReceipt:
        if commitment.campaign_hash != slot.campaign_hash:
            raise ValueError("genesis_h3_v3_audit_campaign_binding_invalid")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{slot.slot_hash}.v3-audit.json"
        if path.exists():
            try:
                receipt = V3DurableAuditReceipt.from_payload(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError("genesis_h3_v3_audit_existing_invalid") from error
            if receipt.slot != slot or receipt.candidate_commitment_hash != commitment.commitment_hash:
                raise ValueError("genesis_h3_v3_audit_reconsumption_rejected")
            return receipt
        claim = path.with_suffix(".claim.json")
        claim_payload = {"candidate_commitment_hash": commitment.commitment_hash}
        claim_data = json.dumps(claim_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary_claim = claim.with_name(f".{claim.name}.{uuid4().hex}.pending")
        descriptor = os.open(temporary_claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        won_claim = False
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(claim_data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_claim, claim)
                won_claim = True
            except FileExistsError:
                try:
                    existing_claim = json.loads(claim.read_text(encoding="utf-8"))
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise ValueError("genesis_h3_v3_audit_claim_invalid") from error
                if existing_claim != claim_payload:
                    raise ValueError("genesis_h3_v3_audit_reconsumption_rejected")
        finally:
            try:
                temporary_claim.unlink()
            except FileNotFoundError:
                pass
        if not won_claim:
            # The first claimant may still be evaluating or may require a
            # recovery receipt.  Never issue a second evaluator invocation.
            raise ValueError("genesis_h3_v3_audit_claim_pending_recovery")
        receipt = V3DurableAuditReceipt(
            "genesis-m7-v3-durable-audit-receipt-h3a0", slot, commitment.commitment_hash, evaluate_once(),
        )
        data = json.dumps(receipt.canonical_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.pending")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise ValueError("genesis_h3_v3_audit_result_conflict")
            return receipt
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True, slots=True)
class V3CampaignAttestation:
    """Terminal V3 evidence identity; lower-level receipts enter only by hash."""

    schema_version: str
    campaign: V3ConfirmatoryCampaignManifest
    launch_hash: str
    terminal_status: V3CampaignTerminalStatus
    terminal_ledger_event_hash: str
    artifact_hashes: tuple[str, ...]
    attestation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != "genesis-m7-v3-campaign-attestation-h3a0":
            raise ValueError("genesis_h3_v3_attestation_schema_invalid")
        _hash(self.launch_hash, "genesis_h3_v3_attestation_launch_invalid")
        _hash(self.terminal_ledger_event_hash, "genesis_h3_v3_attestation_ledger_invalid")
        status = V3CampaignTerminalStatus(self.terminal_status)
        artifacts = tuple(sorted(str(item) for item in self.artifact_hashes))
        if not artifacts or len(set(artifacts)) != len(artifacts):
            raise ValueError("genesis_h3_v3_attestation_artifacts_invalid")
        for value in artifacts:
            _hash(value, "genesis_h3_v3_attestation_artifacts_invalid")
        object.__setattr__(self, "terminal_status", status)
        object.__setattr__(self, "artifact_hashes", artifacts)
        object.__setattr__(self, "attestation_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign": self.campaign.canonical_payload(),
            "launch_hash": self.launch_hash,
            "terminal_status": self.terminal_status.value,
            "terminal_ledger_event_hash": self.terminal_ledger_event_hash,
            "artifact_hashes": self.artifact_hashes,
        }


@dataclass(frozen=True, slots=True)
class V3BatteryClosure:
    """Native V3 aggregation: exact predeclared six, no V2 attestation input."""

    schema_version: str
    predeclaration_hash: str
    battery_manifest_hash: str
    execution_source_manifest_hash: str
    environment_manifest_hash: str
    campaign_attestations: tuple[V3CampaignAttestation, ...]
    status: V3BatteryStatus = field(init=False)
    closure_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not all(isinstance(item, V3CampaignAttestation) for item in self.campaign_attestations):
            raise ValueError("genesis_h3_v3_battery_closure_attestation_type_invalid")
        attestations = tuple(sorted(self.campaign_attestations, key=lambda item: item.campaign.task_id))
        if (
            self.schema_version != "genesis-m7-v3-battery-closure-h3a0"
            or tuple(item.campaign.task_id for item in attestations) != _CANONICAL_TASKS
            or len({item.campaign.campaign_id for item in attestations}) != 6
        ):
            raise ValueError("genesis_h3_v3_battery_closure_identity_invalid")
        for value in (
            self.predeclaration_hash, self.battery_manifest_hash,
            self.execution_source_manifest_hash, self.environment_manifest_hash,
        ):
            _hash(value, "genesis_h3_v3_battery_closure_hash_invalid")
        if any(
            item.campaign.predeclaration_hash != self.predeclaration_hash
            or item.campaign.battery_manifest_hash != self.battery_manifest_hash
            or item.campaign.execution_source_manifest_hash != self.execution_source_manifest_hash
            or item.campaign.environment_manifest_hash != self.environment_manifest_hash
            for item in attestations
        ):
            raise ValueError("genesis_h3_v3_battery_closure_binding_invalid")
        statuses = tuple(item.terminal_status for item in attestations)
        status = (
            V3BatteryStatus.GE_I_BATTERY_SUPPORTED if all(item is V3CampaignTerminalStatus.SUPPORTED for item in statuses)
            else V3BatteryStatus.GE_I_BATTERY_FAIL if any(item is V3CampaignTerminalStatus.FAIL for item in statuses)
            else V3BatteryStatus.GE_I_BATTERY_NOT_PROVEN
        )
        object.__setattr__(self, "campaign_attestations", attestations)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "closure_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "predeclaration_hash": self.predeclaration_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "execution_source_manifest_hash": self.execution_source_manifest_hash,
            "environment_manifest_hash": self.environment_manifest_hash,
            "campaign_attestations": tuple(item.canonical_payload() for item in self.campaign_attestations),
            "status": self.status.value,
        }


def close_v3_confirmatory_battery(*, predeclaration: GEIConfirmatoryPredeclarationV3,
                                  launch: V3ExecutionLaunchReceipt,
                                  attestations: Iterable[V3CampaignAttestation]) -> V3BatteryClosure:
    """Close only the exact six campaigns authorized by a verified V3 launch."""

    if not predeclaration.validate() or launch.predeclaration_hash != predeclaration.predeclaration_hash:
        raise ValueError("genesis_h3_v3_battery_closure_launch_invalid")
    items = tuple(attestations)
    if any(item.launch_hash != launch.launch_hash for item in items):
        raise ValueError("genesis_h3_v3_battery_closure_launch_invalid")
    return V3BatteryClosure(
        "genesis-m7-v3-battery-closure-h3a0", predeclaration.predeclaration_hash,
        predeclaration.battery.battery_manifest_hash,
        predeclaration.execution_source.manifest_hash, predeclaration.environment.manifest_hash,
        items,
    )
