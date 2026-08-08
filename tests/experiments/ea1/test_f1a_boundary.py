from __future__ import annotations

from pathlib import Path

import pytest

from runtime.experiments.ea1.budget import EpistemicBudget
from runtime.experiments.ea1.contracts import Arm, BeliefRevision, ExperimentMemoryRecord, ExperimentProposal, Producer, ScenarioFamily, TheoryState
from runtime.experiments.ea1.evaluator import EvaluationEvidence, FirstCrossingTracker, SourceAcquisitionEvaluator
from runtime.experiments.ea1.harness import (
    EA1_EXECUTION_AUTHORIZATION_FIELD,
    CanonicalOutcomeResolver,
    ExecutionAuthorization,
    NeutralExperimentHarness,
)
from runtime.experiments.ea1.ledger import ExperimentLedger, StorageLedgerBackend
from runtime.experiments.ea1.scenarios import make_smoke_fixture
from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.experience import ExperienceIntegrityError, ExperienceStore
from runtime.organism.life_transition import DynamicLifeChain
from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.canonical_outcomes import ACTING_OWNER, _issue_canonical_outcome_authority


def storage(tmp_path: Path):
    return StorageFactory.create_facade(StorageConfig(mode="sqlite", sqlite_db_path=str(tmp_path / "ea1.db"), postgres_dsn=None, artifact_root=tmp_path / "artifacts", prefer_postgres_reads=False, strict_dual_write=False))


def commit_f1a(storage, *, action_id: str, authorization: ExecutionAuthorization) -> None:
    before = OrganismDynamicState.create(organism_id="organism", lineage_id="lineage", run_id="run", episode_id="episode", life_step=0, logical_time=12, previous_state_hash=None, world={}, regime={}, organism={}, memory={}, neural={}, policy={}, resources={}, homeostasis={})
    after = OrganismDynamicState.create(organism_id="organism", lineage_id="lineage", run_id="run", episode_id="episode", life_step=1, logical_time=13, previous_state_hash=before.state_hash, world={"observed": True}, regime={}, organism={}, memory={}, neural={}, policy={}, resources={}, homeostasis={})
    facts = {"organism_id": "organism", "run_id": "run", "episode_id": "episode", "scenario": "ea1-smoke", "regime": "dev", "main_variable": "signal", "causal_status": "", "intervention": action_id, "viability_margin": .8, "ioc": .7, "risk": .25, "reward": .1, "action": "act", "certified": False, "closure_passed": True, "viability_delta": .1}
    transition = DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run").commit(
        state_before=before, state_after=after, trace_group_id="trace", action_proposals=(), authoritative_decision={EA1_EXECUTION_AUTHORIZATION_FIELD: authorization.to_payload()}, committed_intervention={"intervention": action_id}, external_input=None,
        factual_outcome={"world_state_hash": "world", "experience_facts": facts}, counterfactual_evidence={}, certificate={}, reward={"reward": .1}, memory_delta={}, neural_state_delta={}, policy_delta={}, resource_delta={}, viability_delta={}, regime_before={}, regime_after={}, rollback_refuge_result={},
        outcome_authority=_issue_canonical_outcome_authority(storage=storage, owner=ACTING_OWNER),
    )
    assert transition.status == "committed"


def prepared_harness(storage):
    fixture = make_smoke_fixture(ScenarioFamily.S2)
    ledger = ExperimentLedger(StorageLedgerBackend(storage))
    harness = NeutralExperimentHarness(run_id="run", arm=Arm.EXPERIMENTAL, ledger=ledger, budget=EpistemicBudget())
    state = TheoryState("t1", 1, .49, .49, .02, "h1")
    action = fixture.public.actions[0]
    proposal = ExperimentProposal("p1", 1, action.action_id, "pred", .2, .1, Producer.ORGANISM)
    harness.register_theory(state)
    harness.register_proposals(1, (proposal,), fixture.public.actions)
    receipt, authorization = harness.select(
        1,
        proposal,
        action,
        selector="test",
        organism_id="organism",
        episode_id="episode",
    )
    return harness, ledger, receipt, authorization, action


# T7 — no epistemic object can enter ExperienceStore or SituationWisdom.
def test_t7_epistemic_artifacts_are_rejected_by_experience_store(tmp_path: Path) -> None:
    store = ExperienceStore(storage=storage(tmp_path))
    memory = ExperimentMemoryRecord("em", "run", Arm.EXPERIMENTAL, 1, "rev", {"belief": "h1"})
    with pytest.raises(ExperienceIntegrityError, match="invalid_type"):
        store.record(memory)  # type: ignore[arg-type]
    assert store.wisdom(organism_id="organism", situation="anything").n == 0


def test_t7_production_ea1_never_imports_private_f1a_authority() -> None:
    root = Path(__file__).parents[3] / "runtime" / "experiments" / "ea1"
    source = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "_issue_canonical_outcome_authority" not in source
    assert "CanonicalOutcomeAuthority" not in source


@pytest.mark.parametrize("artifact", [
    ExperimentProposal("p", 1, "a", "pred", .1, .1, Producer.ORGANISM),
    ExperimentMemoryRecord("m", "run", Arm.EXPERIMENTAL, 1, "r", {}),
    BeliefRevision("r", 1, "before", TheoryState("after", 1, .8, .15, .05, "h1", predecessor_state_id="before", version=2, logical_time=2), "out", "reason"),
])
def test_t7_predicted_or_epistemic_artifacts_cannot_mint_observed_outcomes(tmp_path: Path, artifact) -> None:
    db = storage(tmp_path)
    with pytest.raises(Exception):
        db.append_event(event_type="organism.life_transition.committed", run_id="run", source="scenario_episode_runner", payload=artifact.to_payload())
    assert db.list_events(run_id="run", event_types=["organism.life_transition.committed"]) == []


# T8 — real canonical F1A event, selected first, then read-only reference.
def test_t8_real_f1a_outcome_is_resolved_without_duplicate_authority(tmp_path: Path) -> None:
    db = storage(tmp_path)
    harness, ledger, receipt, authorization, action = prepared_harness(db)
    commit_f1a(db, action_id=action.action_id, authorization=authorization)
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    harness.attach_outcome(1, reference, resolver=resolver)
    kinds = [entry.kind for entry in ledger.entries("run")]
    assert kinds == ["theory", "proposal_set", "selection", "outcome_reference"]
    assert reference.committed_intervention == action.action_id


def test_t8_complete_neutral_route_reaches_post_run_acquisition_evaluation(tmp_path: Path) -> None:
    db = storage(tmp_path)
    harness, ledger, receipt, authorization, action = prepared_harness(db)
    commit_f1a(db, action_id=action.action_id, authorization=authorization)
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    harness.attach_outcome(1, reference, resolver=resolver)
    successor = TheoryState("t2", 1, .80, .15, .05, "h1", (reference.reference_id,), predecessor_state_id="t1", version=2, logical_time=20)
    revision = BeliefRevision("rev1", 1, "t1", successor, reference.reference_id, "canonical evidence")
    harness.revise(revision)
    harness.remember(ExperimentMemoryRecord("mem1", "run", Arm.EXPERIMENTAL, 1, "rev1", {}, theory_state_id="t2", selection_receipt_id=receipt.receipt_id, outcome_reference_id=reference.reference_id))
    tracker = FirstCrossingTracker()
    tracker.observe(successor)
    evaluator = SourceAcquisitionEvaluator("run", Arm.EXPERIMENTAL, tracker, scenario_family=ScenarioFamily.S2)
    evaluator.mark_arms_finalized()
    candidate = evaluator.seal_candidate()
    harness.persist_acquisition(candidate)
    final = evaluator.finalize(EvaluationEvidence(True, .50, .45, 2, True, .25, True, False, candidate_canonical_signature="sig", ground_truth_canonical_signature="sig", heldout_interventional_mae=.1, heldout_probe_count=8, functional_probe_count=4, ground_truth_opening_ref="opening"))
    harness.persist_acquisition(final)
    assert [entry.kind for entry in ledger.entries("run")] == ["theory", "proposal_set", "selection", "outcome_reference", "revision", "experiment_memory", "acquisition_candidate", "acquisition_final"]


# T13 persistence survives process-local ledger reconstruction and remains idempotent.
def test_t13_storage_ledger_reconstructs_exact_chain(tmp_path: Path) -> None:
    db = storage(tmp_path)
    _, ledger, _, _, _ = prepared_harness(db)
    reconstructed = ExperimentLedger(StorageLedgerBackend(db))
    assert reconstructed.entries("run") == ledger.entries("run")


# T15 EA1 event persistence does not create experience memory.
def test_t15_experimental_ledger_does_not_change_situation_wisdom(tmp_path: Path) -> None:
    db = storage(tmp_path)
    prepared_harness(db)
    assert ExperienceStore(storage=db).wisdom(organism_id="organism", situation="anything").n == 0
