from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.experiments.ea1.budget import EpistemicBudget
from runtime.experiments.ea1.canonical import canonical_json
from runtime.experiments.ea1.contracts import (
    Arm,
    HypothesisCandidate,
    ScenarioFamily,
    TheoryState,
    artifact_hash,
)
from runtime.experiments.ea1.controls import RandomMatchedCostControl
from runtime.experiments.ea1.harness import NeutralExperimentHarness
from runtime.experiments.ea1.ledger import ExperimentLedger
from runtime.experiments.ea1.mci_adapter import MCITheoryAdapter
from runtime.experiments.ea1.mci_arm import MCIArmAdapter, MCIArmInput
from runtime.experiments.ea1.mci_voi_policy import (
    DECISION_DESIGN_ID,
    LAMBDA_DECISION,
    LAMBDA_RISK,
)
from runtime.experiments.ea1.scenarios import make_smoke_fixture


def initial_theory(*, epoch: int = 1) -> TheoryState:
    return TheoryState(
        "theory-initial",
        epoch,
        0.49,
        0.49,
        0.02,
        "h1",
        rival_hypothesis_ids=("h1", "h2"),
        logical_time=1,
    )


def substrate(family: ScenarioFamily = ScenarioFamily.S2) -> MCIArmInput:
    fixture = make_smoke_fixture(family)
    return MCIArmInput(
        fixture.public,
        initial_theory(),
        fixture.public.hypotheses,
        {"passive_observation": fixture.public.passive_observation.value},
    )


def test_t2_theory_mapping_preserves_identity_structure_scope_and_authority() -> None:
    source = substrate()
    before = tuple(item.to_payload() for item in source.hypotheses)
    working = MCITheoryAdapter().adapt(
        source.theory, source.hypotheses, source.scenario.actions
    )
    assert tuple(item.candidate.to_payload() for item in working.hypotheses) == before
    assert {item.candidate.hypothesis_id for item in working.hypotheses} == {"h1", "h2"}
    assert [item.official_weight for item in working.hypotheses] == [0.49, 0.49]
    assert all(
        item.runtime.learner.hypothesis_ledger.get(item.candidate.hypothesis_id) is not None
        for item in working.hypotheses
    )
    with pytest.raises(Exception, match="authority_disagreement"):
        working.assert_consistent(replace(source.theory, posterior_h1=0.6, posterior_h2=0.38))


def test_t3_only_two_supplied_rivals_exist_and_are_not_mutated() -> None:
    source = substrate()
    extra = replace(source.hypotheses[0], hypothesis_id="h3")
    with pytest.raises(Exception, match="exactly_two"):
        MCITheoryAdapter().adapt(
            source.theory, source.hypotheses + (extra,), source.scenario.actions
        )
    assert tuple(item.hypothesis_id for item in source.hypotheses) == ("h1", "h2")


@pytest.mark.parametrize("family", [ScenarioFamily.S2, ScenarioFamily.S5])
def test_t4_t18_t19_prediction_matrix_is_complete_model_based_and_divergent(family) -> None:
    source = substrate(family)
    batch = MCIArmAdapter().prepare(source, epoch=1, logical_time=2)
    matrix = batch.prediction_set
    assert len(matrix.predictions) == 12
    assert {
        (item.hypothesis_id, item.action_id) for item in matrix.predictions
    } == {
        (hypothesis.hypothesis_id, action.action_id)
        for hypothesis in source.hypotheses
        for action in source.scenario.actions
    }
    assert all(item.evidence_type == "SIMULATED/MODEL_BASED" for item in matrix.predictions)
    assert all(item.model_spec_hash and item.predictor_identity for item in matrix.predictions)
    divergent = {
        action.action_id
        for action in source.scenario.actions
        if len(
            {
                item.success_probability
                for item in matrix.predictions
                if item.action_id == action.action_id
            }
        )
        > 1
    }
    assert len(divergent) == 2
    if family is ScenarioFamily.S5:
        # The scheduled passive observation has Bayes factor one and supplies no policy label.
        assert source.theory == initial_theory()
        assert "discriminating" not in canonical_json(source.scenario)


def test_t5_policy_has_no_private_metadata_or_evaluator_dependency() -> None:
    import inspect
    import runtime.experiments.ea1.mci_voi_policy as policy_module

    text = inspect.getsource(policy_module)
    forbidden = (
        "ground_truth",
        "oracle",
        "SourceAcquisitionEvaluator",
        "heldout",
        "future_outcome",
        "scenario_id",
        "action.label",
    )
    assert all(token not in text for token in forbidden)


def test_t6_exact_frozen_voi_golden_and_boundary_cases() -> None:
    source = substrate()
    batch = MCIArmAdapter().prepare(source, epoch=1, logical_time=2)
    informative = [item for item in batch.proposals if item.discrimination_estimate > 0.0]
    neutral = [item for item in batch.proposals if item.discrimination_estimate == 0.0]
    assert len(informative) == 2 and len(neutral) == 4
    for proposal in informative:
        assert proposal.expected_information_gain == pytest.approx(0.08880913118994371)
        assert proposal.expected_decision_value == pytest.approx(0.0431)
        assert proposal.voi_score == pytest.approx(0.04414365247597747)
        terms = dict(proposal.voi_terms)
        assert terms["lambda_decision"] == LAMBDA_DECISION == 0.5
        assert terms["lambda_risk"] == LAMBDA_RISK == 2.0
        assert terms["denominator"] == 2.5
    assert all(item.expected_information_gain == 0.0 for item in neutral)
    assert all(item.expected_decision_value == 0.0 for item in neutral)
    assert all(item.voi_score == 0.0 for item in neutral)
    assert DECISION_DESIGN_ID == "DECISION_DESIGN_DISTRIBUTION_V1"


def test_unavailable_prediction_is_marked_and_receives_no_fabricated_eig() -> None:
    source = substrate()
    missing_action = source.scenario.actions[0].action_id
    reduced = dict(source.hypotheses[0].intervention_probabilities)
    reduced.pop(missing_action)
    hypotheses = (
        replace(source.hypotheses[0], intervention_probabilities=reduced),
        source.hypotheses[1],
    )
    scenario = replace(source.scenario, hypotheses=hypotheses)
    batch = MCIArmAdapter().prepare(
        replace(source, scenario=scenario, hypotheses=hypotheses),
        epoch=1,
        logical_time=2,
    )
    assert ("h1", missing_action) in batch.prediction_set.unavailable_cells
    proposal = next(item for item in batch.proposals if item.action_id == missing_action)
    assert proposal.admissibility_status == "unavailable"
    assert proposal.expected_information_gain == proposal.expected_decision_value == 0.0
    assert proposal.voi_score == 0.0


def test_t7_action_permutation_and_equal_score_tie_are_hash_stable() -> None:
    source = substrate()
    adapter = MCIArmAdapter()
    batch = adapter.prepare(source, epoch=1, logical_time=2)
    permuted_scenario = replace(source.scenario, actions=tuple(reversed(source.scenario.actions)))
    permuted = adapter.prepare(
        replace(source, scenario=permuted_scenario), epoch=1, logical_time=2
    )
    first = adapter.policy.select(source.theory, batch.proposals)
    second = adapter.policy.select(source.theory, tuple(reversed(permuted.proposals)))
    assert first.selected is not None and second.selected is not None
    assert first.selected.action_id == second.selected.action_id
    assert artifact_hash(first.selected) == artifact_hash(second.selected)
    assert first.tie_break_result.startswith("canonical_hash:")


def test_t8_t9_c2_and_c3_share_exact_batch_and_equal_factual_budget() -> None:
    source = substrate()
    adapter = MCIArmAdapter()
    batch = adapter.prepare(source, epoch=1, logical_time=2)
    c3_ledger, c2_ledger = ExperimentLedger(), ExperimentLedger()
    c3 = NeutralExperimentHarness(
        run_id="c3", arm=Arm.C3_MCI_VOI, ledger=c3_ledger,
        budget=EpistemicBudget(), scenario_family=ScenarioFamily.S2.value,
    )
    c2 = NeutralExperimentHarness(
        run_id="c2", arm=Arm.C2_RANDOM, ledger=c2_ledger,
        budget=EpistemicBudget(), scenario_family=ScenarioFamily.S2.value,
    )
    c3_receipt, c3_auth, _ = adapter.select_c3(c3, batch, epoch=1)
    c2_receipt, c2_auth = adapter.select_c2(
        c2, batch, RandomMatchedCostControl(17, "MCI"), epoch=1
    )
    assert c3_auth is not None and c2_auth is not None
    assert c3_receipt.proposal_set_hash == c2_receipt.proposal_set_hash
    assert c3_receipt.candidate_proposal_ids == c2_receipt.candidate_proposal_ids
    assert c3_receipt.budget_after == c2_receipt.budget_after
    assert c3_receipt.budget_after.tokens_used == 1
    assert batch.compute.factual_interventions == batch.compute.canonical_outcomes == 0
    assert [entry.kind for entry in c3_ledger.entries("c3")] == [
        "theory", "prediction_set", "proposal_set", "selection"
    ]


def test_t10_receipt_seals_full_voi_before_any_outcome() -> None:
    source = substrate()
    adapter = MCIArmAdapter()
    batch = adapter.prepare(source, epoch=1, logical_time=2)
    ledger = ExperimentLedger()
    harness = NeutralExperimentHarness(
        run_id="run", arm=Arm.C3_MCI_VOI, ledger=ledger,
        budget=EpistemicBudget(), scenario_family=ScenarioFamily.S2.value,
    )
    receipt, authorization, _ = adapter.select_c3(harness, batch, epoch=1)
    assert authorization is not None
    assert receipt.theory_state_id == source.theory.state_id
    assert receipt.prediction_set_id == batch.prediction_set.prediction_set_id
    assert receipt.score_components_by_proposal
    assert receipt.tie_break_result
    rendered = canonical_json(receipt)
    assert "outcome_hash" not in rendered and "future_outcome" not in rendered
    assert ledger.entries("run")[-1].kind == "selection"


def test_abstention_is_preregistered_sealed_and_costs_no_token() -> None:
    source = substrate()
    adapter = MCIArmAdapter()
    batch = adapter.prepare(source, epoch=1, logical_time=2)
    no_information = tuple(
        replace(
            item,
            expected_information_gain=0.0,
            expected_decision_value=0.0,
            voi_score=0.0,
            voi_terms=(),
        )
        for item in batch.proposals
    )
    batch.proposals = no_information
    harness = NeutralExperimentHarness(
        run_id="abstain", arm=Arm.C3_MCI_VOI, ledger=ExperimentLedger(),
        budget=EpistemicBudget(), scenario_family=ScenarioFamily.S2.value,
    )
    receipt, authorization, decision = adapter.select_c3(harness, batch, epoch=1)
    assert authorization is None and decision.selected is None
    assert receipt.abstention and receipt.abstention_reason == "no_safe_proposal_meets_eig_threshold"
    assert receipt.budget_before == receipt.budget_after
    assert receipt.budget_after.tokens_used == 0
