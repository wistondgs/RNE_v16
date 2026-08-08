"""Persistent, resumable exactly-once application of H2-bound evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .canonical import canonical_value, digest, stable_id
from .contracts import (
    BeliefRevision,
    CanonicalOutcomeReference,
    ContractError,
    EvidenceApplicationRecord,
    EvidenceApplicationStatus,
    ExperimentSelectionReceipt,
    OrdinalState,
    TheoryState,
)
from .harness import CanonicalOutcomeResolver
from .ledger import ExperimentLedger, LedgerEntry, LedgerIntegrityError, StorageLedgerBackend


class EvidenceApplicationError(ContractError):
    pass


class PersistentAtomicityRequired(EvidenceApplicationError):
    pass


class InjectedApplicationCrash(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceApplicationResult:
    application: EvidenceApplicationRecord
    revision: BeliefRevision
    successor: TheoryState
    retry_result: str


def evidence_application_id(
    receipt: ExperimentSelectionReceipt,
    reference: CanonicalOutcomeReference,
    prior: TheoryState,
) -> str:
    return stable_id(
        "ea1-evidence-application",
        {
            "selection_receipt_id": receipt.receipt_id,
            "execution_id": receipt.execution_id,
            "outcome_reference_id": reference.reference_id,
            "prior_theory_state_id": prior.state_id,
        },
    )


class EvidenceApplicationService:
    """Makes the official revision ledger effect deterministic and resumable.

    Persistence uses the EA1 append-only ledger. Its storage-backed event identity
    is the atomic exclusion primitive; in-memory ledgers are intentionally refused.
    """

    BEFORE_RESERVE = "before_reserve"
    AFTER_RESERVE = "after_reserve"
    AFTER_REVISION = "after_revision"
    BEFORE_COMMIT = "before_commit"

    def __init__(
        self,
        ledger: ExperimentLedger,
        resolver: CanonicalOutcomeResolver,
    ) -> None:
        if not isinstance(ledger.backend, StorageLedgerBackend):
            raise PersistentAtomicityRequired("persistent_atomic_ledger_required")
        self.ledger = ledger
        self.resolver = resolver

    def apply(
        self,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
        prior: TheoryState,
        revision: BeliefRevision,
        *,
        inject_failure: str | None = None,
    ) -> EvidenceApplicationResult:
        # H2 remains the first authority gate on every initial or retry attempt.
        self.resolver.validate(receipt, reference)
        self._persisted_inputs(receipt, reference, prior)
        application_id = evidence_application_id(receipt, reference, prior)
        canonical_revision = self._canonical_revision(
            application_id, receipt, reference, prior, revision
        )
        reserved = self._record(
            application_id,
            receipt,
            reference,
            prior,
            canonical_revision,
            EvidenceApplicationStatus.RESERVED,
        )
        committed = replace(
            reserved,
            status=EvidenceApplicationStatus.COMMITTED,
            committed_logical_position=receipt.logical_time + 4,
        )

        initial = self._application_entries(receipt.run_id, application_id)
        self._reject_forged_or_divergent_records(
            receipt.run_id, receipt, reference, prior, application_id, reserved
        )
        committed_entry = self._one(initial, "evidence_application_committed")
        if committed_entry is not None:
            self._assert_payload(committed_entry, committed)
            persisted_revision = self._persisted_revision(
                receipt.run_id, canonical_revision
            )
            return EvidenceApplicationResult(
                committed,
                persisted_revision,
                persisted_revision.theory_after,
                "already_committed",
            )

        if inject_failure == self.BEFORE_RESERVE:
            raise InjectedApplicationCrash(self.BEFORE_RESERVE)

        reserved_entry = self._one(initial, "evidence_application_reserved")
        recovered_reservation = reserved_entry is not None
        if reserved_entry is None:
            reserved_entry, _ = self.ledger.append(
                run_id=receipt.run_id,
                arm=receipt.arm.value,
                logical_time=reserved.created_logical_position,
                kind="evidence_application_reserved",
                artifact=reserved,
            )
        self._assert_payload(reserved_entry, reserved)

        if inject_failure == self.AFTER_RESERVE:
            raise InjectedApplicationCrash(self.AFTER_RESERVE)

        revision_entry = self._revision_entry(receipt.run_id, canonical_revision.revision_id)
        recovered_revision = revision_entry is not None
        if revision_entry is None:
            revision_entry, _ = self.ledger.append(
                run_id=receipt.run_id,
                arm=receipt.arm.value,
                logical_time=receipt.logical_time + 3,
                kind="revision",
                artifact=canonical_revision,
            )
        self._assert_payload(revision_entry, canonical_revision)

        if inject_failure == self.AFTER_REVISION:
            raise InjectedApplicationCrash(self.AFTER_REVISION)
        if inject_failure == self.BEFORE_COMMIT:
            raise InjectedApplicationCrash(self.BEFORE_COMMIT)

        commit_entry = self._one(
            self._application_entries(receipt.run_id, application_id),
            "evidence_application_committed",
        )
        if commit_entry is None:
            commit_entry, _ = self.ledger.append(
                run_id=receipt.run_id,
                arm=receipt.arm.value,
                logical_time=receipt.logical_time + 4,
                kind="evidence_application_committed",
                artifact=committed,
            )
        self._assert_payload(commit_entry, committed)
        persisted_revision = self._persisted_revision(
            receipt.run_id, canonical_revision
        )
        if recovered_revision:
            retry_result = "recovered_revision"
        elif recovered_reservation:
            retry_result = "recovered_reservation"
        else:
            retry_result = "applied"
        return EvidenceApplicationResult(
            committed,
            persisted_revision,
            persisted_revision.theory_after,
            retry_result,
        )

    def _canonical_revision(
        self,
        application_id: str,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
        prior: TheoryState,
        draft: BeliefRevision,
    ) -> BeliefRevision:
        if (
            receipt.theory_state_id != prior.state_id
            or receipt.epoch != prior.epoch
            or draft.epoch != receipt.epoch
            or draft.theory_before_id != prior.state_id
            or draft.outcome_reference_id != reference.reference_id
        ):
            raise EvidenceApplicationError("selection_predecessor_mismatch")
        successor = draft.theory_after
        if (
            successor.predecessor_state_id != prior.state_id
            or successor.version != prior.version + 1
            or successor.logical_time <= prior.logical_time
            or successor.epoch < prior.epoch
            or application_id in prior.evidence_ids
        ):
            raise EvidenceApplicationError("revision_lineage_invalid")
        if successor.evidence_ids not in {
            prior.evidence_ids,
            prior.evidence_ids + (application_id,),
        }:
            raise EvidenceApplicationError("revision_evidence_history_invalid")
        evidence_ids = prior.evidence_ids + (application_id,)
        successor_without_id = replace(
            successor,
            state_id="pending",
            evidence_ids=evidence_ids,
            predecessor_state_id=prior.state_id,
            version=prior.version + 1,
        )
        state_identity = {
            key: value
            for key, value in successor_without_id.to_payload().items()
            if key != "state_id"
        }
        successor_id = stable_id(
            "ea1-theory-successor",
            {"application_id": application_id, "state": state_identity},
        )
        canonical_successor = replace(successor_without_id, state_id=successor_id)
        revision_without_id = replace(
            draft,
            revision_id="pending",
            theory_before_id=prior.state_id,
            theory_after=canonical_successor,
            outcome_reference_id=reference.reference_id,
        )
        revision_identity = {
            key: value
            for key, value in revision_without_id.to_payload().items()
            if key != "revision_id"
        }
        revision_id = stable_id(
            "ea1-belief-revision",
            {"application_id": application_id, "revision": revision_identity},
        )
        return replace(revision_without_id, revision_id=revision_id)

    @staticmethod
    def _record(
        application_id: str,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
        prior: TheoryState,
        revision: BeliefRevision,
        status: EvidenceApplicationStatus,
    ) -> EvidenceApplicationRecord:
        return EvidenceApplicationRecord(
            application_id=application_id,
            run_id=receipt.run_id,
            arm=receipt.arm,
            epoch=receipt.epoch,
            selection_receipt_id=receipt.receipt_id,
            execution_id=receipt.execution_id,
            authorization_id=receipt.authorization_id,
            outcome_reference_id=reference.reference_id,
            witness_id=reference.witness_id,
            prior_theory_state_id=prior.state_id,
            revision_id=revision.revision_id,
            successor_theory_state_id=revision.theory_after.state_id,
            revision_payload_hash=digest(revision.to_payload()),
            status=status,
            created_logical_position=receipt.logical_time + 2,
        )

    def _application_entries(
        self, run_id: str, application_id: str
    ) -> tuple[LedgerEntry, ...]:
        return tuple(
            entry
            for entry in self.ledger.entries(run_id)
            if entry.artifact_id == application_id
            and entry.kind
            in {"evidence_application_reserved", "evidence_application_committed"}
        )

    def _persisted_inputs(
        self,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
        prior: TheoryState,
    ) -> None:
        theory_entries = [
            entry
            for entry in self.ledger.entries(receipt.run_id)
            if entry.kind == "theory" and entry.artifact_id == receipt.theory_state_id
        ]
        if (
            len(theory_entries) != 1
            or dict(theory_entries[0].payload) != canonical_value(prior.to_payload())
        ):
            raise EvidenceApplicationError("persisted_predecessor_mismatch")
        reference_entries = [
            entry
            for entry in self.ledger.entries(receipt.run_id)
            if entry.kind == "outcome_reference"
            and entry.artifact_id == reference.reference_id
        ]
        if (
            len(reference_entries) != 1
            or dict(reference_entries[0].payload)
            != canonical_value(reference.to_payload())
        ):
            raise EvidenceApplicationError("persisted_outcome_reference_mismatch")

    def _reject_forged_or_divergent_records(
        self,
        run_id: str,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
        prior: TheoryState,
        application_id: str,
        expected: EvidenceApplicationRecord,
    ) -> None:
        related = []
        for entry in self.ledger.entries(run_id):
            if entry.kind not in {
                "evidence_application_reserved",
                "evidence_application_committed",
            }:
                continue
            payload = entry.payload
            if (
                payload.get("selection_receipt_id") == receipt.receipt_id
                and payload.get("outcome_reference_id") == reference.reference_id
                and payload.get("prior_theory_state_id") == prior.state_id
            ):
                related.append(entry)
        if any(entry.artifact_id != application_id for entry in related):
            raise EvidenceApplicationError("forged_application_id")
        for entry in related:
            expected_payload = (
                replace(
                    expected,
                    status=EvidenceApplicationStatus.COMMITTED,
                    committed_logical_position=receipt.logical_time + 4,
                )
                if entry.kind == "evidence_application_committed"
                else expected
            )
            self._assert_payload(entry, expected_payload)

    @staticmethod
    def _one(
        entries: tuple[LedgerEntry, ...], kind: str
    ) -> LedgerEntry | None:
        matches = [entry for entry in entries if entry.kind == kind]
        if len(matches) > 1:
            raise EvidenceApplicationError("duplicate_application_stage")
        return matches[0] if matches else None

    def _revision_entry(self, run_id: str, revision_id: str) -> LedgerEntry | None:
        matches = [
            entry
            for entry in self.ledger.entries(run_id)
            if entry.kind == "revision" and entry.artifact_id == revision_id
        ]
        if len(matches) > 1:
            raise EvidenceApplicationError("duplicate_revision_identity")
        return matches[0] if matches else None

    @staticmethod
    def _assert_payload(entry: LedgerEntry, artifact: Any) -> None:
        if dict(entry.payload) != canonical_value(artifact.to_payload()):
            raise LedgerIntegrityError("divergent_evidence_application_replay")

    def _persisted_revision(
        self, run_id: str, expected: BeliefRevision
    ) -> BeliefRevision:
        entry = self._revision_entry(run_id, expected.revision_id)
        if entry is None:
            raise EvidenceApplicationError("application_revision_missing")
        self._assert_payload(entry, expected)
        return _revision_from_payload(entry.payload)


def _theory_from_payload(raw: Mapping[str, Any]) -> TheoryState:
    return TheoryState(
        state_id=str(raw["state_id"]),
        epoch=int(raw["epoch"]),
        posterior_h1=float(raw["posterior_h1"]),
        posterior_h2=float(raw["posterior_h2"]),
        posterior_unknown=float(raw["posterior_unknown"]),
        preferred_hypothesis_id=str(raw["preferred_hypothesis_id"]),
        evidence_ids=tuple(raw.get("evidence_ids") or ()),
        rival_hypothesis_ids=tuple(raw.get("rival_hypothesis_ids") or ()),
        ordinal_state=OrdinalState(str(raw["ordinal_state"])),
        predecessor_state_id=(
            str(raw["predecessor_state_id"])
            if raw.get("predecessor_state_id") is not None
            else None
        ),
        version=int(raw["version"]),
        logical_time=int(raw["logical_time"]),
    )


def _revision_from_payload(raw: Mapping[str, Any]) -> BeliefRevision:
    return BeliefRevision(
        revision_id=str(raw["revision_id"]),
        epoch=int(raw["epoch"]),
        theory_before_id=str(raw["theory_before_id"]),
        theory_after=_theory_from_payload(raw["theory_after"]),
        outcome_reference_id=str(raw["outcome_reference_id"]),
        rationale=str(raw["rationale"]),
        likelihood_support=tuple(tuple(item) for item in raw.get("likelihood_support") or ()),
        posterior_weights=tuple(tuple(item) for item in raw.get("posterior_weights") or ()),
        ordinal_transitions=tuple(tuple(item) for item in raw.get("ordinal_transitions") or ()),
        retracted_hypothesis_ids=tuple(raw.get("retracted_hypothesis_ids") or ()),
        unresolved_hypothesis_ids=tuple(raw.get("unresolved_hypothesis_ids") or ()),
        provenance=str(raw.get("provenance") or "canonical_f1a_evidence"),
    )
