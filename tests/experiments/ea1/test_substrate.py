from __future__ import annotations

from dataclasses import fields

import pytest

from runtime.experiments.ea1.budget import BudgetExhausted, EpistemicBudget
from runtime.experiments.ea1.canonical import CanonicalizationError, canonical_json, digest, stable_id
from runtime.experiments.ea1.contracts import (
    AcquisitionStatus, Arm, BeliefRevision, CensorReason, ContractError,
    DivergentPrediction, DivergentPredictionSet, ExperimentMemoryRecord,
    ExperimentProposal, HypothesisCandidate, OrdinalState, PredictionMode,
    Producer, PublicAction, ScenarioFamily, TheoryState,
)
from runtime.experiments.ea1.controls import GreedyControl, PassiveControl, RandomMatchedCostControl
from runtime.experiments.ea1.evaluator import EvaluationEvidence, EvaluationPhaseError, FirstCrossingTracker, SourceAcquisitionEvaluator
from runtime.experiments.ea1.harness import NeutralExperimentHarness, TemporalOrderError
from runtime.experiments.ea1.ledger import ExperimentLedger, InMemoryLedgerBackend, LedgerIntegrityError
from runtime.experiments.ea1.scenarios import make_smoke_fixture
from runtime.experiments.ea1.sealing import OracleService, SealAccessError


def theory(epoch: int = 1, h1: float = .49, h2: float = .49, unknown: float = .02, suffix: str = "a") -> TheoryState:
    return TheoryState(f"theory-{suffix}", epoch, h1, h2, unknown, "h1")


def proposal(action: PublicAction, epoch: int = 1, suffix: str = "a", reward: float = 0.1) -> ExperimentProposal:
    return ExperimentProposal(f"proposal-{suffix}", epoch, action.action_id, "predictions", .2, reward, Producer.ORGANISM)


def harness_ready():
    fixture = make_smoke_fixture(ScenarioFamily.S2)
    ledger, budget = ExperimentLedger(), EpistemicBudget()
    harness = NeutralExperimentHarness(run_id="run", arm=Arm.EXPERIMENTAL, ledger=ledger, budget=budget)
    harness.register_theory(theory())
    p = proposal(fixture.public.actions[0])
    harness.register_proposals(1, (p,), fixture.public.actions)
    return fixture, ledger, budget, harness, p


# T1 — contracts, normalization, invalid states, hashes.
def test_t1_contract_hashes_are_canonical_and_invalid_states_fail() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert digest({"a": 2, "b": 1}) == digest({"b": 1, "a": 2})
    with pytest.raises(CanonicalizationError):
        digest({"x": float("nan")})
    with pytest.raises(ContractError):
        theory(h1=.8, h2=.3, unknown=.02)
    with pytest.raises(ContractError):
        PublicAction("x", "x", {}, cost=2)


def test_t1_prediction_set_requires_real_divergence_and_candidates_are_typed() -> None:
    HypothesisCandidate("opaque-h1", "class-a", "x causes y", "preregistered")
    same = DivergentPrediction("h1", "a", PredictionMode.INTERVENTIONAL, OrdinalState.HIGH, 1)
    with pytest.raises(ContractError):
        DivergentPredictionSet("set", (same, same))


def test_t1_selection_receipt_has_no_hidden_or_outcome_fields() -> None:
    from runtime.experiments.ea1.contracts import ExperimentSelectionReceipt
    names = {field.name for field in fields(ExperimentSelectionReceipt)}
    assert not names & {"hidden_mechanism", "true_structural_class", "outcome", "discriminating", "nonce"}


# T2 — temporal order.
def test_t2_outcome_and_revision_cannot_precede_selection() -> None:
    _, _, _, harness, _ = harness_ready()
    with pytest.raises(TemporalOrderError):
        harness.attach_outcome(1, object())  # type: ignore[arg-type]


# T3/T4 — hidden ground truth and oracle isolation.
@pytest.mark.parametrize("family", [ScenarioFamily.S2, ScenarioFamily.S3, ScenarioFamily.S5])
def test_t3_public_scenario_exposes_no_hidden_fields(family: ScenarioFamily) -> None:
    fixture = make_smoke_fixture(family)
    rendered = canonical_json(fixture.public)
    for forbidden in ("true_structural", "discriminating_action", "oracle_action", "outcomes", "nonce"):
        assert forbidden not in rendered


def test_t4_oracle_requires_private_capability() -> None:
    fixture = make_smoke_fixture(ScenarioFamily.S5)
    with pytest.raises(SealAccessError):
        fixture.sealed_ground_truth.open(object(), purpose="oracle")
    oracle = OracleService(fixture.sealed_ground_truth, fixture.sealed_ground_truth.oracle_token())
    assert oracle.choose(fixture.public.actions) in fixture.public.actions


# T5 — four equal tokens, replay, hard limits.
def test_t5_shared_budget_exact_limits_and_idempotent_replay() -> None:
    action = PublicAction("a", "a", {})
    budget = EpistemicBudget()
    first = budget.consume("one", action, 1)
    assert budget.consume("one", action, 1) is first
    for epoch in range(2, 5):
        budget.consume(str(epoch), action, epoch)
    assert budget.snapshot.tokens_used == 4 and budget.snapshot.cost_used == 4 and budget.snapshot.risk_used == 1.0
    with pytest.raises(BudgetExhausted):
        budget.consume("five", action, 4)


def test_t5_abstention_costs_nothing() -> None:
    budget = EpistemicBudget()
    assert budget.abstain(1).tokens_used == 0


# T6 — matched random changes selector only.
def test_t6_matched_random_uses_same_public_proposals_and_is_reproducible() -> None:
    fixture = make_smoke_fixture(ScenarioFamily.S2)
    proposals = tuple(proposal(a, suffix=str(i)) for i, a in enumerate(fixture.public.actions))
    mci, a11 = RandomMatchedCostControl(17, "MCI"), RandomMatchedCostControl(17, "A11")
    assert mci.select(proposals, fixture.public.actions) == a11.select(proposals, fixture.public.actions)
    assert mci.draw_index == a11.draw_index == 1
    assert PassiveControl().select(proposals, fixture.public.actions) is None
    assert GreedyControl().select(proposals, fixture.public.actions) in proposals


# T9 — revision predecessor/successor is explicit and ledger persisted.
def test_t9_revision_contract_carries_versioned_predecessor_and_successor() -> None:
    after = theory(epoch=2, h1=.8, h2=.15, unknown=.05, suffix="after")
    revision = BeliefRevision("rev", 1, "theory-a", after, "outcome-ref", "Bayes update")
    assert revision.theory_before_id != revision.theory_after.state_id
    assert revision.to_payload()["theory_after"] is after


# T10/T11 — frozen boundaries and first crossing.
def valid_evidence(**overrides):
    values = dict(correct_structural_class=True, heldout_initial_log_loss=.50, heldout_acquired_log_loss=.45,
                  persistence_opportunities=2, persistence_passed=True, functional_gain=.25,
                  canonical_evidence=True, prohibited_information=False,
                  candidate_canonical_signature="sig", ground_truth_canonical_signature="sig",
                  heldout_interventional_mae=.10, heldout_probe_count=8,
                  functional_probe_count=4, ground_truth_opening_ref="opening")
    values.update(overrides)
    return EvaluationEvidence(**values)


def evaluator_with_crossing() -> SourceAcquisitionEvaluator:
    tracker = FirstCrossingTracker()
    tracker.observe(theory(h1=.80, h2=.15, unknown=.05, suffix="cross"))
    evaluator = SourceAcquisitionEvaluator("run", Arm.EXPERIMENTAL, tracker)
    evaluator.mark_arms_finalized()
    evaluator.seal_candidate()
    return evaluator


def test_t10_all_acquisition_boundaries_are_conjunctive() -> None:
    assert evaluator_with_crossing().finalize(valid_evidence()).status is AcquisitionStatus.VALID
    failures = (
        {"correct_structural_class": False},
        {"heldout_acquired_log_loss": .451},
        {"candidate_canonical_signature": "other"},
        {"heldout_interventional_mae": .100001},
        {"persistence_opportunities": 1},
        {"persistence_passed": False},
        {"functional_gain": .249999},
        {"functional_invariant_breaches": 1},
        {"canonical_evidence": False},
        {"prohibited_information": True},
    )
    for change in failures:
        assert evaluator_with_crossing().finalize(valid_evidence(**change)).status is AcquisitionStatus.INVALID


def test_t10_evaluator_cannot_operate_during_run() -> None:
    evaluator = SourceAcquisitionEvaluator("run", Arm.EXPERIMENTAL, FirstCrossingTracker())
    with pytest.raises(EvaluationPhaseError):
        evaluator.seal_candidate()


def test_t11_first_crossing_is_exact_and_immutable_after_regression() -> None:
    tracker = FirstCrossingTracker()
    assert tracker.observe(theory(suffix="pre")) is None
    crossing = theory(epoch=2, h1=.80, h2=.15, unknown=.05, suffix="first")
    assert tracker.observe(crossing) is crossing
    tracker.observe(theory(epoch=3, suffix="regress"))
    later = theory(epoch=4, h1=.90, h2=.05, unknown=.05, suffix="later")
    assert tracker.observe(later) is crossing
    assert tracker.regressed_after_crossing


@pytest.mark.parametrize("state", [
    TheoryState("posterior-boundary", 1, .80, .15, .05, "h1"),
    TheoryState("odds-boundary", 1, .80, .20, .00, "h1"),
    TheoryState("unknown-boundary", 1, .80, .10, .10, "h1"),
])
def test_t11_threshold_boundaries_cross_exactly(state: TheoryState) -> None:
    assert FirstCrossingTracker().observe(state) is state


def test_t11_completed_run_without_crossing_is_invalid_not_success() -> None:
    evaluator = SourceAcquisitionEvaluator("run", Arm.EXPERIMENTAL, FirstCrossingTracker())
    evaluator.mark_arms_finalized()
    evaluator.seal_candidate()
    assert evaluator.finalize(valid_evidence()).status is AcquisitionStatus.INVALID


# T12 — every censor state is non-success.
@pytest.mark.parametrize("reason", [r for r in CensorReason if r is not CensorReason.NONE])
def test_t12_censoring_never_becomes_success(reason: CensorReason) -> None:
    result = evaluator_with_crossing().finalize(valid_evidence(censor_reason=reason))
    assert result.status is AcquisitionStatus.INCOMPLETE


def test_t12_zero_evaluations_is_incomplete() -> None:
    result = evaluator_with_crossing().finalize(valid_evidence(evaluation_count=0))
    assert result.status is AcquisitionStatus.INCOMPLETE
    assert result.censor_reason is CensorReason.ZERO_EVALUATIONS


# T13 — ledger replay and divergence.
def test_t13_exact_ledger_replay_is_idempotent_and_divergence_fails_closed() -> None:
    backend, ledger = InMemoryLedgerBackend(), ExperimentLedger()
    ledger.backend = backend
    state = theory()
    first, appended = ledger.append(run_id="r", arm="experimental", logical_time=10, kind="theory", artifact=state)
    replay, replay_appended = ledger.append(run_id="r", arm="experimental", logical_time=10, kind="theory", artifact=state)
    assert appended and not replay_appended and replay == first and len(backend.rows) == 1
    divergent = TheoryState(state.state_id, 1, .8, .15, .05, "h1")
    with pytest.raises(LedgerIntegrityError, match="divergent_replay"):
        ledger.append(run_id="r", arm="experimental", logical_time=10, kind="theory", artifact=divergent)
    assert ledger.quarantined("r")


# T14 — fixture integrity.
@pytest.mark.parametrize("family", [ScenarioFamily.S2, ScenarioFamily.S3, ScenarioFamily.S5])
def test_t14_exactly_two_hidden_discriminators_and_four_nondiscriminators(family: ScenarioFamily) -> None:
    fixture = make_smoke_fixture(family)
    hidden = fixture.sealed_ground_truth.open(fixture.sealed_ground_truth.evaluator_token(), purpose="evaluator")
    assert len(hidden["discriminating_action_ids"]) == 2
    assert len(hidden["non_discriminating_action_ids"]) == 4
    assert hidden["passive_bayes_factor"] == 1.0


def test_t14_s3_delays_outcome_until_horizon() -> None:
    fixture = make_smoke_fixture(ScenarioFamily.S3)
    action = fixture.public.actions[0].action_id
    assert fixture.outcome(action, fixture.public.outcome_horizon - 1) is None
    assert isinstance(fixture.outcome(action, fixture.public.outcome_horizon), OrdinalState)


def test_t14_p3a_cannot_generate_confirm_fixtures() -> None:
    with pytest.raises(ContractError):
        make_smoke_fixture(ScenarioFamily.S2, split="CONFIRM")


# T15 — import/fixture construction is inert.
def test_t15_feature_isolation_has_no_environment_or_storage_side_effects(monkeypatch) -> None:
    import os
    before = dict(os.environ)
    make_smoke_fixture(ScenarioFamily.S1)
    assert dict(os.environ) == before
