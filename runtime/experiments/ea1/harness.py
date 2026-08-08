from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from runtime.organism.experience import ExperienceIntegrityError, outcome_witness_from_event
from runtime.storage import StorageFacade

from .budget import EpistemicBudget
from .canonical import digest, stable_id
from .contracts import (
    Arm, BeliefRevision, CanonicalOutcomeReference, ExperimentMemoryRecord,
    ExperimentProposal, ExperimentSelectionReceipt, PublicAction, TheoryState,
    SourceAcquisitionReceipt, AcquisitionStatus,
)
from .ledger import ExperimentLedger


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
    action_id: str
    intervention: str


class CanonicalOutcomeResolver:
    """Read-only F1A bridge: resolves an already persisted factual event."""

    def __init__(self, storage: StorageFacade) -> None:
        self.storage = storage

    def resolve(self, receipt: ExperimentSelectionReceipt, *, organism_id: str, episode_id: str) -> CanonicalOutcomeReference:
        events = self.storage.list_events(run_id=receipt.run_id, event_types=["organism.life_transition.committed"], limit=10000)
        matches = []
        for event in events:
            try:
                witness = outcome_witness_from_event(event)
            except ExperienceIntegrityError:
                continue
            if witness.organism_id == organism_id and witness.episode_id == episode_id and witness.committed_intervention == receipt.action_id:
                matches.append(witness)
        if len(matches) != 1:
            raise ExperienceIntegrityError("ea1_requires_exactly_one_matching_canonical_outcome")
        witness = matches[0]
        payload = {"selection_receipt_id": receipt.receipt_id, "witness_id": witness.witness_id}
        return CanonicalOutcomeReference(
            reference_id=stable_id("outref", payload), selection_receipt_id=receipt.receipt_id,
            source_event_type=witness.source_event_type, source_record_id=witness.source_record_id,
            witness_id=witness.witness_id, committed_intervention=witness.committed_intervention,
            outcome_hash=witness.outcome_hash,
        )


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

    def select(self, epoch: int, proposal: ExperimentProposal, action: PublicAction, *, selector: str, random_seed: int | None = None, random_draw_index: int | None = None) -> tuple[ExperimentSelectionReceipt, ExecutionAuthorization]:
        self._require(epoch, EpochPhase.PROPOSALS)
        if proposal not in self._proposals[epoch] or proposal.action_id != action.action_id:
            raise ValueError("selection_not_in_registered_proposal_set")
        base = {"run_id": self.run_id, "arm": self.arm.value, "epoch": epoch, "proposal_id": proposal.proposal_id, "action_id": action.action_id}
        receipt_id = stable_id("select", base)
        consumption = self.budget.consume(receipt_id, action, epoch)
        from .contracts import ScenarioFamily
        receipt = ExperimentSelectionReceipt(
            receipt_id, self.run_id, self.arm, epoch, proposal.proposal_id, action.action_id,
            selector, random_seed, random_draw_index, consumption.before, consumption.after,
            digest([p.to_payload() for p in self._proposals[epoch]]), self.block_id,
            ScenarioFamily(self.scenario_family), tuple(p.proposal_id for p in self._proposals[epoch]),
            tuple((p.proposal_id, p.expected_information_gain) for p in self._proposals[epoch]), epoch * 10 + 2,
        )
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=epoch * 10 + 2, kind="selection", artifact=receipt)
        self._selection[epoch], self._phase[epoch] = receipt, EpochPhase.SELECTED
        auth = ExecutionAuthorization(stable_id("execauth", receipt.to_payload()), receipt.receipt_id, action.action_id, action.action_id)
        return receipt, auth

    def attach_outcome(self, epoch: int, reference: CanonicalOutcomeReference) -> None:
        self._require(epoch, EpochPhase.SELECTED)
        receipt = self._selection[epoch]
        if reference.selection_receipt_id != receipt.receipt_id or reference.committed_intervention != receipt.action_id:
            raise ExperienceIntegrityError("outcome_does_not_match_sealed_selection")
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=epoch * 10 + 3, kind="outcome_reference", artifact=reference)
        self._outcome[epoch], self._phase[epoch] = reference, EpochPhase.OUTCOME

    def revise(self, revision: BeliefRevision) -> None:
        self._require(revision.epoch, EpochPhase.OUTCOME)
        if revision.outcome_reference_id != self._outcome[revision.epoch].reference_id or revision.theory_before_id != self._theory[revision.epoch].state_id:
            raise ValueError("revision_provenance_mismatch")
        before = self._theory[revision.epoch]
        if revision.theory_after.predecessor_state_id != before.state_id or revision.theory_after.version != before.version + 1 or revision.theory_after.logical_time <= before.logical_time:
            raise ValueError("revision_version_chain_invalid")
        self.ledger.append(run_id=self.run_id, arm=self.arm.value, logical_time=revision.epoch * 10 + 4, kind="revision", artifact=revision)
        self._phase[revision.epoch] = EpochPhase.REVISED

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
