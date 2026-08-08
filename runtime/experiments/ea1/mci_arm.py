"""C3 MCI adapter wiring; factual execution remains in NeutralExperimentHarness/F1A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .canonical import digest
from .contracts import (
    DivergentPredictionSet,
    ExperimentProposal,
    ExperimentSelectionReceipt,
    HypothesisCandidate,
    PublicAction,
    TheoryState,
)
from .controls import RandomMatchedCostControl
from .harness import ExecutionAuthorization, NeutralExperimentHarness
from .mci_adapter import MCIPredictionAdapter, MCITheoryAdapter, MCIWorkingSet
from .mci_voi_policy import MCISelectionDecision, MCI_VOI_Policy, POLICY_ID


class PublicScenarioLike(Protocol):
    actions: tuple[PublicAction, ...]
    hypotheses: tuple[HypothesisCandidate, ...]
    outcome_horizon: int

    def to_payload(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MCIArmInput:
    scenario: PublicScenarioLike
    theory: TheoryState
    hypotheses: tuple[HypothesisCandidate, ...]
    public_state: Mapping[str, Any]

    @property
    def public_hash(self) -> str:
        return digest(
            {
                "scenario": self.scenario,
                "theory": self.theory,
                "hypotheses": self.hypotheses,
                "public_state": self.public_state,
            }
        )


@dataclass(frozen=True, slots=True)
class MCIComputeReceipt:
    substrate_hash: str
    transition_simulations: int
    factual_interventions: int
    canonical_outcomes: int


@dataclass(slots=True)
class MCIProposalBatch:
    substrate: MCIArmInput
    working: MCIWorkingSet
    prediction_set: DivergentPredictionSet
    proposals: tuple[ExperimentProposal, ...]
    compute: MCIComputeReceipt


class MCIArmAdapter:
    def __init__(self) -> None:
        self.theory_adapter = MCITheoryAdapter()
        self.prediction_adapter = MCIPredictionAdapter()
        self.policy = MCI_VOI_Policy()

    def prepare(self, substrate: MCIArmInput, *, epoch: int, logical_time: int) -> MCIProposalBatch:
        if substrate.hypotheses != substrate.scenario.hypotheses:
            raise ValueError("arm_hypotheses_must_equal_public_scenario_hypotheses")
        working = self.theory_adapter.adapt(
            substrate.theory,
            substrate.hypotheses,
            substrate.scenario.actions,
        )
        predictions = self.prediction_adapter.predict(
            working,
            substrate.theory,
            substrate.scenario.actions,
            public_state=substrate.public_state,
            horizon=substrate.scenario.outcome_horizon,
            logical_time=logical_time,
        )
        proposals = self.policy.proposals(
            substrate.theory,
            predictions,
            substrate.scenario.actions,
            epoch=epoch,
        )
        return MCIProposalBatch(
            substrate,
            working,
            predictions,
            proposals,
            MCIComputeReceipt(substrate.public_hash, len(predictions.predictions), 0, 0),
        )

    def select_c3(
        self,
        harness: NeutralExperimentHarness,
        batch: MCIProposalBatch,
        *,
        epoch: int,
        governance: tuple[tuple[str, str], ...] = (),
    ) -> tuple[ExperimentSelectionReceipt, ExecutionAuthorization | None, MCISelectionDecision]:
        harness.register_theory(batch.substrate.theory)
        harness.register_predictions(epoch, batch.prediction_set)
        harness.register_proposals(epoch, batch.proposals, batch.substrate.scenario.actions)
        decision = self.policy.select(batch.substrate.theory, batch.proposals, governance=governance)
        if decision.selected is None:
            receipt = harness.abstain(
                epoch,
                selector=POLICY_ID,
                reason=decision.abstention_reason,
                tie_break_result=decision.tie_break_result,
            )
            return receipt, None, decision
        action = self._action(batch.substrate.scenario.actions, decision.selected.action_id)
        receipt, authorization = harness.select(
            epoch,
            decision.selected,
            action,
            selector=POLICY_ID,
            tie_break_result=decision.tie_break_result,
        )
        return receipt, authorization, decision

    def select_c2(
        self,
        harness: NeutralExperimentHarness,
        batch: MCIProposalBatch,
        control: RandomMatchedCostControl,
        *,
        epoch: int,
    ) -> tuple[ExperimentSelectionReceipt, ExecutionAuthorization]:
        harness.register_theory(batch.substrate.theory)
        harness.register_predictions(epoch, batch.prediction_set)
        harness.register_proposals(epoch, batch.proposals, batch.substrate.scenario.actions)
        selected = control.select(batch.proposals, batch.substrate.scenario.actions)
        if selected is None:
            raise ValueError("matched_random_requires_nonempty_mci_proposals")
        action = self._action(batch.substrate.scenario.actions, selected.action_id)
        return harness.select(
            epoch,
            selected,
            action,
            selector=f"c2_random_matched_cost[{control.substrate_tag}]",
            random_seed=control.seed,
            random_draw_index=control.draw_index - 1,
            tie_break_result="counter_based_rng_over_canonical_proposal_hashes",
        )

    @staticmethod
    def _action(actions: tuple[PublicAction, ...], action_id: str) -> PublicAction:
        return next(item for item in actions if item.action_id == action_id)
