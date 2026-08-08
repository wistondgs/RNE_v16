from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping

from runtime.organism.experience import ExperienceIntegrityError, outcome_witness_from_event
from runtime.organism.life_transition import LifeTransition
from runtime.storage import StorageFacade

from .budget import EpistemicBudget
from .canonical import canonical_value, digest, stable_id
from .contracts import (
    Arm, BeliefRevision, CanonicalOutcomeReference, ExperimentMemoryRecord,
    ExperimentProposal, ExperimentSelectionReceipt, PublicAction, TheoryState,
    SourceAcquisitionReceipt, AcquisitionStatus,
)
from .ledger import ExperimentLedger


EA1_EXECUTION_AUTHORIZATION_FIELD = "ea1_execution_authorization"


class TemporalOrderError(RuntimeError):
    pass


class EpochPhase(IntEnum):
    INITIAL = 0
    THEORY = 1
    PROPOSALS = 2
    SELECTED = 3
    OUTCOME = 4
    REVISED = 5
    REMEMBERED = 6


@dataclass(frozen=True, slots=True)
class ExecutionAuthorization:
    authorization_id: str
    selection_receipt_id: str
    execution_id: str
    run_id: str
    arm: Arm
    epoch: int
    organism_id: str
    episode_id: str
    action_id: str
    intervention: str
    selection_logical_time: int
    authorization_token: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "selection_receipt_id": self.selection_receipt_id,
            "execution_id": self.execution_id,
            "run_id": self.run_id,
            "arm": self.arm.value,
            "epoch": self.epoch,
            "organism_id": self.organism_id,
            "episode_id": self.episode_id,
            "action_id": self.action_id,
            "intervention": self.intervention,
            "selection_logical_time": self.selection_logical_time,
            "authorization_token": self.authorization_token,
        }


def _selection_identity_payload(
    *,
    run_id: str,
    arm: Arm,
    epoch: int,
    proposal_id: str,
    action_id: str,
    block_id: str,
    scenario_family: str,
    organism_id: str,
    episode_id: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "arm": arm.value,
        "epoch": epoch,
        "proposal_id": proposal_id,
        "action_id": action_id,
        "block_id": block_id,
        "scenario_family": scenario_family,
        "organism_id": organism_id,
        "episode_id": episode_id,
    }


def _authorization_for_receipt(
    receipt: ExperimentSelectionReceipt, authorization_token: str
) -> ExecutionAuthorization:
    return ExecutionAuthorization(
        receipt.authorization_id,
        receipt.receipt_id,
        receipt.execution_id,
        receipt.run_id,
        receipt.arm,
        receipt.epoch,
        receipt.organism_id,
        receipt.episode_id,
        receipt.action_id,
        receipt.action_id,
        receipt.logical_time,
        authorization_token,
    )


class CanonicalOutcomeResolver:
    """Binds one persisted EA1 selection to one later, revalidated F1A outcome."""

    def __init__(self, storage: StorageFacade, ledger: ExperimentLedger) -> None:
        self.storage = storage
        self.ledger = ledger

    def resolve(
        self, receipt: ExperimentSelectionReceipt
    ) -> CanonicalOutcomeReference:
        self._persisted_selection(receipt)
        matches: list[tuple[Any, Any]] = []
        for event in self.storage.list_events(
            run_id=receipt.run_id,
            event_types=["organism.life_transition.committed"],
            limit=10000,
        ):
            try:
                witness = outcome_witness_from_event(event)
            except ExperienceIntegrityError:
                continue
            if (
                witness.organism_id == receipt.organism_id
                and witness.episode_id == receipt.episode_id
                and witness.committed_intervention == receipt.action_id
            ):
                matches.append((event, witness))
        if len(matches) != 1:
            raise ExperienceIntegrityError(
                "ea1_requires_exactly_one_bound_canonical_outcome"
            )
        event, witness = matches[0]
        transition = LifeTransition.from_dict(event.payload)
        reference_payload = {
            "selection_receipt_id": receipt.receipt_id,
            "execution_id": receipt.execution_id,
            "witness_id": witness.witness_id,
        }
        reference = CanonicalOutcomeReference(
            reference_id=stable_id("outref", reference_payload),
            selection_receipt_id=receipt.receipt_id,
            source_event_type=witness.source_event_type,
            source_record_id=witness.source_record_id,
            witness_id=witness.witness_id,
            committed_intervention=witness.committed_intervention,
            outcome_hash=witness.outcome_hash,
            execution_id=receipt.execution_id,
            authorization_id=receipt.authorization_id,
            organism_id=witness.organism_id,
            episode_id=witness.episode_id,
            canonical_event_logical_time=transition.state_after.logical_time,
        )
        self.validate(receipt, reference)
        return reference

    def validate(
        self,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
    ) -> None:
        if not isinstance(reference, CanonicalOutcomeReference):
            raise ExperienceIntegrityError("canonical_outcome_reference_required")
        self._persisted_selection(receipt)
        if reference.selection_receipt_id != receipt.receipt_id:
            raise ExperienceIntegrityError("canonical_reference_selection_mismatch")
        if reference.execution_id != receipt.execution_id:
            raise ExperienceIntegrityError("canonical_reference_execution_mismatch")
        expected_reference_id = stable_id(
            "outref",
            {
                "selection_receipt_id": receipt.receipt_id,
                "execution_id": receipt.execution_id,
                "witness_id": reference.witness_id,
            },
        )
        if reference.reference_id != expected_reference_id:
            raise ExperienceIntegrityError("canonical_reference_id_mismatch")

        matches: list[tuple[Any, Any]] = []
        for event in self.storage.list_events(
            run_id=receipt.run_id,
            event_types=[reference.source_event_type],
            limit=10000,
        ):
            try:
                witness = outcome_witness_from_event(event)
            except ExperienceIntegrityError:
                continue
            if witness.source_record_id == reference.source_record_id:
                matches.append((event, witness))
        if len(matches) != 1:
            raise ExperienceIntegrityError(
                "canonical_reference_does_not_resolve_uniquely"
            )
        event, witness = matches[0]
        if witness.witness_id != reference.witness_id:
            raise ExperienceIntegrityError("canonical_reference_witness_mismatch")
        if witness.outcome_hash != reference.outcome_hash:
            raise ExperienceIntegrityError("canonical_reference_outcome_mismatch")
        if witness.source_run_id != receipt.run_id:
            raise ExperienceIntegrityError("outcome_run_mismatch")
        if witness.organism_id != receipt.organism_id:
            raise ExperienceIntegrityError("outcome_organism_mismatch")
        if witness.episode_id != receipt.episode_id:
            raise ExperienceIntegrityError("outcome_episode_mismatch")
        if witness.committed_intervention != receipt.action_id:
            raise ExperienceIntegrityError("outcome_action_mismatch")
        if (
            reference.organism_id != witness.organism_id
            or reference.episode_id != witness.episode_id
            or reference.committed_intervention != witness.committed_intervention
            or reference.authorization_id != receipt.authorization_id
        ):
            raise ExperienceIntegrityError("canonical_reference_binding_mismatch")

        try:
            transition = LifeTransition.from_dict(event.payload)
        except (TypeError, ValueError) as exc:
            raise ExperienceIntegrityError("canonical_transition_invalid") from exc
        if (
            transition.state_before.run_id != receipt.run_id
            or transition.state_after.run_id != receipt.run_id
        ):
            raise ExperienceIntegrityError("outcome_run_mismatch")
        event_logical_time = transition.state_after.logical_time
        if (
            transition.state_before.logical_time < receipt.logical_time
            or event_logical_time <= receipt.logical_time
            or event_logical_time <= transition.state_before.logical_time
        ):
            raise ExperienceIntegrityError("outcome_precedes_selection")
        if reference.canonical_event_logical_time != event_logical_time:
            raise ExperienceIntegrityError("canonical_event_logical_time_mismatch")

        raw_authorization = transition.authoritative_decision.get(
            EA1_EXECUTION_AUTHORIZATION_FIELD
        )
        if not isinstance(raw_authorization, Mapping):
            raise ExperienceIntegrityError("execution_binding_missing")
        authorization_token = str(raw_authorization.get("authorization_token") or "")
        expected_authorization_id = stable_id(
            "execauth",
            {
                "execution_id": receipt.execution_id,
                "authorization_token": authorization_token,
            },
        )
        if expected_authorization_id != receipt.authorization_id:
            raise ExperienceIntegrityError("execution_authorization_mismatch")
        expected_authorization = _authorization_for_receipt(
            receipt, authorization_token
        )
        if dict(raw_authorization) != expected_authorization.to_payload():
            raise ExperienceIntegrityError("execution_authorization_mismatch")

    def _persisted_selection(self, receipt: ExperimentSelectionReceipt) -> None:
        if not isinstance(receipt, ExperimentSelectionReceipt):
            raise ExperienceIntegrityError("selection_receipt_required")
        identity = _selection_identity_payload(
            run_id=receipt.run_id,
            arm=receipt.arm,
            epoch=receipt.epoch,
            proposal_id=receipt.proposal_id,
            action_id=receipt.action_id,
            block_id=receipt.block_id,
            scenario_family=receipt.scenario_family.value,
            organism_id=receipt.organism_id,
            episode_id=receipt.episode_id,
        )
        if (
            receipt.receipt_id != stable_id("select", identity)
            or receipt.execution_id != stable_id("ea1-execution", identity)
        ):
            raise ExperienceIntegrityError("selection_receipt_identity_mismatch")
        matches = [
            entry
            for entry in self.ledger.entries(receipt.run_id)
            if entry.kind == "selection" and entry.artifact_id == receipt.receipt_id
        ]
        if len(matches) != 1:
            raise ExperienceIntegrityError("selection_receipt_not_persisted")
        entry = matches[0]
        if (
            entry.arm != receipt.arm.value
            or entry.logical_time != receipt.logical_time
            or dict(entry.payload) != canonical_value(receipt.to_payload())
        ):
            raise ExperienceIntegrityError("persisted_selection_receipt_mismatch")


class NeutralExperimentHarness:
    def __init__(self, *, run_id: str, arm: Arm, ledger: ExperimentLedger, budget: EpistemicBudget, block_id: str = "block-dev", scenario_family: str = "s1") -> None:
        self.run_id, self.arm, self.ledger, self.budget = run_id, arm, ledger, budget
        self.block_id, self.scenario_family = block_id, scenario_family
        self._phase: dict[int, EpochPhase] = {}
        self._theory: dict[int, TheoryState] = {}
        self._proposals: dict[int, tuple[ExperimentProposal, ...]] = {}
        self._selection: dict[int, ExperimentSelectionReceipt] = {}
        self._outcome: dict[int, CanonicalOutcomeReference] = {}

    def _require(self, epoch: int, phase: EpochPhase) -> None:
        if self._phase.get(epoch, EpochPhase.INITIAL) != phase:
            raise TemporalOrderError(f"expected_{phase.name.lower()}")

    def register_theory(self, state: TheoryState) -> None:
        self._require(state.epoch, EpochPhase.INITIAL)
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=state.epoch * 10, kind="theory", artifact=state)
        self._theory[state.epoch], self._phase[state.epoch] = state, EpochPhase.THEORY

    def register_proposals(self, epoch: int, proposals: tuple[ExperimentProposal, ...], actions: tuple[PublicAction, ...]) -> None:
        self._require(epoch, EpochPhase.THEORY)
        if len(actions) != 6 or len({a.action_id for a in actions}) != 6:
            raise ValueError("ea1_requires_exactly_six_public_actions")
        action_ids = {action.action_id for action in actions}
        if not proposals or any(p.epoch != epoch or p.action_id not in action_ids for p in proposals) or len({p.proposal_id for p in proposals}) != len(proposals):
            raise ValueError("invalid_proposal_set")
        wrapper = _ProposalSet(stable_id("props", [p.to_payload() for p in proposals]), proposals)
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=epoch * 10 + 1, kind="proposal_set", artifact=wrapper)
        self._proposals[epoch], self._phase[epoch] = proposals, EpochPhase.PROPOSALS

    def select(self, epoch: int, proposal: ExperimentProposal, action: PublicAction, *, selector: str, organism_id: str, episode_id: str, random_seed: int | None = None, random_draw_index: int | None = None) -> tuple[ExperimentSelectionReceipt, ExecutionAuthorization]:
        self._require(epoch, EpochPhase.PROPOSALS)
        if proposal not in self._proposals[epoch] or proposal.action_id != action.action_id:
            raise ValueError("selection_not_in_registered_proposal_set")
        if not organism_id.strip() or not episode_id.strip():
            raise ValueError("selection_execution_identity_required")
        from .contracts import ScenarioFamily
        scenario_family = ScenarioFamily(self.scenario_family)
        base = _selection_identity_payload(
            run_id=self.run_id,
            arm=self.arm,
            epoch=epoch,
            proposal_id=proposal.proposal_id,
            action_id=action.action_id,
            block_id=self.block_id,
            scenario_family=scenario_family.value,
            organism_id=organism_id,
            episode_id=episode_id,
        )
        receipt_id = stable_id("select", base)
        execution_id = stable_id("ea1-execution", base)
        authorization_token = secrets.token_hex(32)
        authorization_id = stable_id(
            "execauth",
            {
                "execution_id": execution_id,
                "authorization_token": authorization_token,
            },
        )
        consumption = self.budget.consume(receipt_id, action, epoch)
        receipt = ExperimentSelectionReceipt(
            receipt_id=receipt_id,
            run_id=self.run_id,
            arm=self.arm,
            epoch=epoch,
            proposal_id=proposal.proposal_id,
            action_id=action.action_id,
            selector=selector,
            random_seed=random_seed,
            random_draw_index=random_draw_index,
            budget_before=consumption.before,
            budget_after=consumption.after,
            proposal_set_hash=digest(
                [p.to_payload() for p in self._proposals[epoch]]
            ),
            execution_id=execution_id,
            authorization_id=authorization_id,
            organism_id=organism_id,
            episode_id=episode_id,
            theory_state_id=self._theory[epoch].state_id,
            block_id=self.block_id,
            scenario_family=scenario_family,
            candidate_proposal_ids=tuple(
                p.proposal_id for p in self._proposals[epoch]
            ),
            scores_available=tuple(
                (p.proposal_id, p.expected_information_gain)
                for p in self._proposals[epoch]
            ),
            logical_time=epoch * 10 + 2,
        )
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=epoch * 10 + 2, kind="selection", artifact=receipt)
        self._selection[epoch], self._phase[epoch] = receipt, EpochPhase.SELECTED
        auth = _authorization_for_receipt(receipt, authorization_token)
        return receipt, auth

    def attach_outcome(
        self,
        epoch: int,
        reference: CanonicalOutcomeReference,
        *,
        resolver: CanonicalOutcomeResolver | None = None,
    ) -> None:
        self._require(epoch, EpochPhase.SELECTED)
        receipt = self._selection[epoch]
        if not isinstance(resolver, CanonicalOutcomeResolver):
            raise ExperienceIntegrityError("canonical_outcome_resolver_required")
        resolver.validate(receipt, reference)
        if reference.selection_receipt_id != receipt.receipt_id or reference.committed_intervention != receipt.action_id:
            raise ExperienceIntegrityError("outcome_does_not_match_sealed_selection")
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=epoch * 10 + 3, kind="outcome_reference", artifact=reference)
        self._outcome[epoch], self._phase[epoch] = reference, EpochPhase.OUTCOME

    def revise(
        self,
        revision: BeliefRevision,
        *,
        application_service: Any | None = None,
    ) -> BeliefRevision:
        self._require(revision.epoch, EpochPhase.OUTCOME)
        if revision.outcome_reference_id != self._outcome[revision.epoch].reference_id or revision.theory_before_id != self._theory[revision.epoch].state_id:
            raise ValueError("revision_provenance_mismatch")
        before = self._theory[revision.epoch]
        if revision.theory_after.predecessor_state_id != before.state_id or revision.theory_after.version != before.version + 1 or revision.theory_after.logical_time <= before.logical_time:
            raise ValueError("revision_version_chain_invalid")
        from .application import EvidenceApplicationService

        if not isinstance(application_service, EvidenceApplicationService):
            raise ValueError("persistent_evidence_application_service_required")
        result = application_service.apply(
            self._selection[revision.epoch],
            self._outcome[revision.epoch],
            before,
            revision,
        )
        self._theory[revision.epoch] = result.successor
        self._phase[revision.epoch] = EpochPhase.REVISED
        return result.revision

    def remember(self, memory: ExperimentMemoryRecord) -> None:
        self._require(memory.epoch, EpochPhase.REVISED)
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=memory.epoch * 10 + 5, kind="experiment_memory", artifact=memory)
        self._phase[memory.epoch] = EpochPhase.REMEMBERED

    def persist_acquisition(self, receipt: SourceAcquisitionReceipt) -> None:
        if receipt.run_id != self.run_id or receipt.arm is not self.arm:
            raise ValueError("acquisition_identity_mismatch")
        if not self._phase or any(phase < EpochPhase.REVISED for phase in self._phase.values()):
            raise TemporalOrderError("acquisition_requires_completed_revision")
        kind = "acquisition_candidate" if receipt.status is AcquisitionStatus.CANDIDATE_SEALED else "acquisition_final"
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=max(entry.logical_time for entry in self.ledger.entries(self.run_id)) + 1, kind=kind, artifact=receipt)


@dataclass(frozen=True, slots=True)
class _ProposalSet:
    proposal_set_id: str
    proposals: tuple[ExperimentProposal, ...]
    def to_payload(self) -> dict[str, Any]:
        return {"proposal_set_id": self.proposal_set_id, "proposals": self.proposals}
