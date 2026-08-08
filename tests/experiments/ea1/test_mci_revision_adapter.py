from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from runtime.experiments.ea1.budget import EpistemicBudget
from runtime.experiments.ea1.contracts import (
    Arm,
    ExperimentMemoryRecord,
    ScenarioFamily,
    TheoryState,
)
from runtime.experiments.ea1.harness import CanonicalOutcomeResolver, NeutralExperimentHarness
from runtime.experiments.ea1.ledger import ExperimentLedger, StorageLedgerBackend
from runtime.experiments.ea1.mci_adapter import (
    MCIPredictionAdapter,
    MCIStateRestorer,
)
from runtime.experiments.ea1.mci_arm import MCIArmAdapter, MCIArmInput
from runtime.experiments.ea1.mci_revision_adapter import (
    CanonicalEvidenceBridge,
    MCIOutcomeAdapter,
)
from runtime.experiments.ea1.scenarios import make_smoke_fixture
from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.experience import ExperienceIntegrityError, ExperienceStore
from runtime.organism.life_transition import DynamicLifeChain
from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.canonical_outcomes import ACTING_OWNER, _issue_canonical_outcome_authority


def storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "ea1-mci.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def initial_theory() -> TheoryState:
    return TheoryState(
        "theory-initial", 1, 0.49, 0.49, 0.02, "h1",
        rival_hypothesis_ids=("h1", "h2"), logical_time=1,
    )


def commit_f1a(
    db,
    *,
    run_id: str,
    episode_id: str,
    action_id: str,
    outcome: int,
    logical_time: int,
) -> str:
    organism_id = f"organism-{episode_id}"
    before = OrganismDynamicState.create(
        organism_id=organism_id, lineage_id="lineage", run_id=run_id,
        episode_id=episode_id, life_step=0, logical_time=logical_time,
        previous_state_hash=None, world={}, regime={}, organism={}, memory={}, neural={},
        policy={}, resources={}, homeostasis={},
    )
    after = OrganismDynamicState.create(
        organism_id=organism_id, lineage_id="lineage", run_id=run_id,
        episode_id=episode_id, life_step=1, logical_time=logical_time + 1,
        previous_state_hash=before.state_hash, world={"ea1_binary_outcome": outcome},
        regime={}, organism={}, memory={}, neural={}, policy={}, resources={}, homeostasis={},
    )
    facts = {
        "organism_id": organism_id, "run_id": run_id, "episode_id": episode_id,
        "scenario": "ea1-mci-dev", "regime": "dev", "main_variable": "binary_outcome",
        "causal_status": "", "intervention": action_id, "viability_margin": 0.8,
        "ioc": 0.7, "risk": 0.25, "reward": float(outcome), "action": "act",
        "certified": False, "closure_passed": True, "viability_delta": 0.0,
    }
    transition = DynamicLifeChain(
        organism_id=organism_id, lineage_id="lineage", run_id=run_id
    ).commit(
        state_before=before,
        state_after=after,
        trace_group_id=f"trace-{episode_id}",
        action_proposals=(),
        authoritative_decision={},
        committed_intervention={"intervention": action_id},
        external_input=None,
        factual_outcome={
            "world_state_hash": after.state_hash,
            "ea1_binary_outcome": outcome,
            "experience_facts": facts,
        },
        counterfactual_evidence={}, certificate={}, reward={"reward": float(outcome)},
        memory_delta={}, neural_state_delta={}, policy_delta={}, resource_delta={},
        viability_delta={}, regime_before={}, regime_after={}, rollback_refuge_result={},
        outcome_authority=_issue_canonical_outcome_authority(storage=db, owner=ACTING_OWNER),
    )
    assert transition.status == "committed"
    return organism_id


def custom_substrate(
    *,
    family: ScenarioFamily = ScenarioFamily.S2,
    action_pairs: tuple[tuple[float, float], ...] | None = None,
) -> MCIArmInput:
    fixture = make_smoke_fixture(family)
    actions = fixture.public.actions
    if action_pairs is None:
        hypotheses = fixture.public.hypotheses
    else:
        if len(action_pairs) != 6:
            raise ValueError("six action pairs required")
        h1 = {action.action_id: action_pairs[index][0] for index, action in enumerate(actions)}
        h2 = {action.action_id: action_pairs[index][1] for index, action in enumerate(actions)}
        hypotheses = (
            replace(fixture.public.hypotheses[0], intervention_probabilities=h1),
            replace(fixture.public.hypotheses[1], intervention_probabilities=h2),
        )
    scenario = replace(fixture.public, hypotheses=hypotheses)
    return MCIArmInput(
        scenario,
        initial_theory(),
        hypotheses,
        {"passive_observation": scenario.passive_observation.value},
    )


def start_selected_epoch(db, source: MCIArmInput, *, run_id: str = "run"):
    adapter = MCIArmAdapter()
    batch = adapter.prepare(source, epoch=source.theory.epoch, logical_time=2)
    ledger = ExperimentLedger(StorageLedgerBackend(db))
    harness = NeutralExperimentHarness(
        run_id=run_id, arm=Arm.C3_MCI_VOI, ledger=ledger, budget=EpistemicBudget(),
        scenario_family=source.scenario.family.value,
    )
    receipt, authorization, decision = adapter.select_c3(
        harness, batch, epoch=source.theory.epoch
    )
    assert authorization is not None and decision.selected is not None
    return adapter, batch, ledger, harness, receipt


def resolve_outcome(db, harness, receipt, *, episode_id: str, outcome: int, logical_time: int):
    organism_id = commit_f1a(
        db, run_id=receipt.run_id, episode_id=episode_id, action_id=receipt.action_id,
        outcome=outcome, logical_time=logical_time,
    )
    reference = CanonicalOutcomeResolver(db).resolve(
        receipt, organism_id=organism_id, episode_id=episode_id
    )
    harness.attach_outcome(receipt.epoch, reference)
    return reference


def test_t11_t12_canonical_bridge_accepts_only_revalidated_f1a_reference(tmp_path: Path) -> None:
    db = storage(tmp_path)
    source = custom_substrate()
    _, batch, _, harness, receipt = start_selected_epoch(db, source)
    reference = resolve_outcome(
        db, harness, receipt, episode_id="episode-1", outcome=1, logical_time=10
    )
    bridge = CanonicalEvidenceBridge(db)
    evidence = bridge.validate(reference, receipt)
    assert bridge.owns(evidence) and evidence.outcome == 1
    MCIOutcomeAdapter(bridge).reject_unvalidated(evidence)
    with pytest.raises(ExperienceIntegrityError, match="validated_canonical"):
        MCIOutcomeAdapter(bridge).reject_unvalidated({"outcome": 1})
    fake = replace(reference, outcome_hash="simulated")
    with pytest.raises(ExperienceIntegrityError, match="witness_mismatch"):
        bridge.validate(fake, receipt)
    with pytest.raises(ExperienceIntegrityError, match="reference_required"):
        bridge.validate(batch.prediction_set, receipt)  # type: ignore[arg-type]


def test_t13_belief_revision_uses_exact_preregistered_bayes_rule(tmp_path: Path) -> None:
    db = storage(tmp_path)
    source = custom_substrate()
    _, batch, _, harness, receipt = start_selected_epoch(db, source)
    reference = resolve_outcome(
        db, harness, receipt, episode_id="episode-1", outcome=1, logical_time=10
    )
    revision = MCIOutcomeAdapter(CanonicalEvidenceBridge(db)).revise(
        source.theory, batch.working, batch.prediction_set, receipt, reference,
        epoch=1, logical_time=20,
    )
    probabilities = {
        item.hypothesis_id: item.success_probability
        for item in batch.prediction_set.predictions
        if item.action_id == receipt.action_id
    }
    masses = (0.49 * probabilities["h1"], 0.49 * probabilities["h2"], 0.02 * 0.5)
    total = sum(masses)
    assert revision.theory_after.posterior_h1 == pytest.approx(masses[0] / total)
    assert revision.theory_after.posterior_h2 == pytest.approx(masses[1] / total)
    assert revision.theory_after.posterior_unknown == pytest.approx(masses[2] / total)
    assert revision.theory_after.predecessor_state_id == source.theory.state_id
    assert revision.theory_after.version == 2
    assert revision.provenance == "canonical_f1a_evidence"
    assert revision.mci_state_hash and revision.outcome_reference_id == reference.reference_id


def test_t14_nondiscriminating_evidence_creates_no_artificial_certainty_or_overlay(tmp_path: Path) -> None:
    db = storage(tmp_path)
    source = custom_substrate()
    adapter = MCIArmAdapter()
    batch = adapter.prepare(source, epoch=1, logical_time=2)
    neutral = next(item for item in batch.proposals if item.discrimination_estimate == 0.0)
    action = next(item for item in source.scenario.actions if item.action_id == neutral.action_id)
    ledger = ExperimentLedger(StorageLedgerBackend(db))
    harness = NeutralExperimentHarness(
        run_id="run", arm=Arm.C3_MCI_VOI, ledger=ledger, budget=EpistemicBudget(),
        scenario_family=ScenarioFamily.S2.value,
    )
    harness.register_theory(source.theory)
    harness.register_proposals(1, batch.proposals, source.scenario.actions)
    receipt, _ = harness.select(1, neutral, action, selector="dev-nondiscriminating")
    reference = resolve_outcome(
        db, harness, receipt, episode_id="episode-1", outcome=1, logical_time=10
    )
    revision = MCIOutcomeAdapter(CanonicalEvidenceBridge(db)).revise(
        source.theory, batch.working, batch.prediction_set, receipt, reference,
        epoch=1, logical_time=20,
    )
    assert revision.theory_after.posterior_h1 == pytest.approx(0.49)
    assert revision.theory_after.posterior_h2 == pytest.approx(0.49)
    assert revision.theory_after.posterior_unknown == pytest.approx(0.02)
    assert not revision.retracted_hypothesis_ids
    assert all(item.runtime.learner.active_overlay is None for item in batch.working.hypotheses)


def test_t15_conflicting_canonical_evidence_can_reverse_previous_support(tmp_path: Path) -> None:
    db = storage(tmp_path)
    source = custom_substrate(action_pairs=((0.99, 0.01),) + ((0.5, 0.5),) * 5)
    arm, batch1, ledger, harness, receipt1 = start_selected_epoch(db, source)
    bridge = CanonicalEvidenceBridge(db)
    updater = MCIOutcomeAdapter(bridge)
    ref1 = resolve_outcome(
        db, harness, receipt1, episode_id="episode-1", outcome=1, logical_time=10
    )
    rev1 = updater.revise(
        source.theory, batch1.working, batch1.prediction_set, receipt1, ref1,
        epoch=1, logical_time=20,
    )
    harness.revise(rev1)
    harness.remember(
        ExperimentMemoryRecord(
            "memory-1", "run", Arm.C3_MCI_VOI, 1, rev1.revision_id,
            {"mci_snapshot": batch1.working.snapshot()}, theory_state_id=rev1.theory_after.state_id,
            selection_receipt_id=receipt1.receipt_id, outcome_reference_id=ref1.reference_id,
        )
    )
    assert rev1.theory_after.posterior_h1 > 0.95 and "h2" in rev1.retracted_hypothesis_ids

    source2 = replace(source, theory=rev1.theory_after)
    batch2 = arm.prepare(source2, epoch=2, logical_time=21)
    harness.register_theory(rev1.theory_after)
    harness.register_proposals(2, batch2.proposals, source.scenario.actions)
    selected = next(item for item in batch2.proposals if item.action_id == receipt1.action_id)
    action = next(item for item in source.scenario.actions if item.action_id == receipt1.action_id)
    receipt2, _ = harness.select(2, selected, action, selector="conflict-recheck")
    ref2 = resolve_outcome(
        db, harness, receipt2, episode_id="episode-2", outcome=0, logical_time=30
    )
    rev2 = updater.revise(
        rev1.theory_after, batch2.working, batch2.prediction_set, receipt2, ref2,
        epoch=2, logical_time=40,
    )
    assert rev2.theory_after.posterior_h1 < rev1.theory_after.posterior_h1
    assert rev2.theory_after.posterior_h2 > rev1.theory_after.posterior_h2
    assert rev2.theory_after.posterior_h1 == pytest.approx(
        rev2.theory_after.posterior_h2
    )
    assert rev2.theory_after.posterior_unknown > source.theory.posterior_unknown
    assert "h2" not in rev2.retracted_hypothesis_ids


def test_t16_t17_persistence_reload_rebuilds_mci_and_changes_next_selection(tmp_path: Path) -> None:
    db = storage(tmp_path)
    pairs = ((0.15, 0.85), (0.05, 0.7)) + ((0.5, 0.5),) * 4
    source = custom_substrate(action_pairs=pairs)
    arm, batch, ledger, harness, receipt = start_selected_epoch(db, source)
    first_action = receipt.action_id
    assert first_action == source.scenario.actions[0].action_id
    reference = resolve_outcome(
        db, harness, receipt, episode_id="episode-1", outcome=0, logical_time=10
    )
    revision = MCIOutcomeAdapter(CanonicalEvidenceBridge(db)).revise(
        source.theory, batch.working, batch.prediction_set, receipt, reference,
        epoch=1, logical_time=20,
    )
    harness.revise(revision)
    assert revision.theory_after.posterior_h1 > revision.theory_after.posterior_h2
    snapshot = batch.working.snapshot()
    harness.remember(
        ExperimentMemoryRecord(
            "memory-1", "run", Arm.C3_MCI_VOI, 1, revision.revision_id,
            {"mci_snapshot": snapshot}, theory_state_id=revision.theory_after.state_id,
            proposal_set_id=batch.prediction_set.prediction_set_id,
            selection_receipt_id=receipt.receipt_id, outcome_reference_id=reference.reference_id,
        )
    )

    reconstructed = ExperimentLedger(StorageLedgerBackend(db))
    restored_theory, restored_working = MCIStateRestorer().restore(
        reconstructed, "run", source.hypotheses, source.scenario.actions
    )
    assert restored_theory == revision.theory_after
    assert restored_working.snapshot() == snapshot
    predictions = MCIPredictionAdapter().predict(
        restored_working, restored_theory, source.scenario.actions,
        public_state=source.public_state, horizon=source.scenario.outcome_horizon,
        logical_time=21,
    )
    proposals = arm.policy.proposals(
        restored_theory, predictions, source.scenario.actions, epoch=2
    )
    next_decision = arm.policy.select(restored_theory, proposals)
    assert next_decision.selected is not None
    assert next_decision.selected.action_id == source.scenario.actions[1].action_id
    assert next_decision.selected.action_id != first_action


def test_t20_exact_revision_replay_is_idempotent_and_divergence_fails_closed(tmp_path: Path) -> None:
    db = storage(tmp_path)
    source = custom_substrate()
    _, batch, ledger, harness, receipt = start_selected_epoch(db, source)
    reference = resolve_outcome(
        db, harness, receipt, episode_id="episode-1", outcome=1, logical_time=10
    )
    updater = MCIOutcomeAdapter(CanonicalEvidenceBridge(db))
    first = updater.revise(
        source.theory, batch.working, batch.prediction_set, receipt, reference,
        epoch=1, logical_time=20,
    )
    snapshot_after_first = batch.working.snapshot()
    replay = updater.revise(
        source.theory, batch.working, batch.prediction_set, receipt, reference,
        epoch=1, logical_time=20,
    )
    assert replay is first
    assert batch.working.snapshot() == snapshot_after_first
    assert harness.budget.snapshot.tokens_used == 1
    assert sum(entry.kind == "selection" for entry in ledger.entries("run")) == 1
    ledger.append(
        run_id="run", arm=Arm.C3_MCI_VOI.value, logical_time=14,
        kind="revision", artifact=first,
    )
    _, appended = ledger.append(
        run_id="run", arm=Arm.C3_MCI_VOI.value, logical_time=14,
        kind="revision", artifact=first,
    )
    assert not appended
    assert sum(entry.kind == "revision" for entry in ledger.entries("run")) == 1
    with pytest.raises(Exception, match="divergent_belief_revision_replay"):
        updater.revise(
            source.theory, batch.working, batch.prediction_set, receipt, reference,
            epoch=1, logical_time=21,
        )


def test_t21_f1a_firewall_and_no_circular_evaluation_dependency(tmp_path: Path) -> None:
    import inspect
    import runtime.experiments.ea1.mci_adapter as adapter_module
    import runtime.experiments.ea1.mci_arm as arm_module
    import runtime.experiments.ea1.mci_revision_adapter as revision_module
    import runtime.experiments.ea1.mci_voi_policy as policy_module

    source = "\n".join(
        inspect.getsource(module)
        for module in (adapter_module, arm_module, revision_module, policy_module)
    )
    assert "_issue_canonical_outcome_authority" not in source
    assert "CanonicalOutcomeAuthority" not in source
    assert "SourceAcquisitionEvaluator" not in source
    assert "SituationWisdom" not in source
    assert "ExperienceStore" not in source
    assert "runtime.neural" not in source

    db = storage(tmp_path)
    store = ExperienceStore(storage=db)
    with pytest.raises(ExperienceIntegrityError):
        store.record(initial_theory())  # type: ignore[arg-type]
    assert store.wisdom(organism_id="organism", situation="ea1").n == 0


def test_overlay_updates_cannot_modify_hidden_world_or_evaluator_state(tmp_path: Path) -> None:
    db = storage(tmp_path)
    fixture = make_smoke_fixture(ScenarioFamily.S2)
    token = fixture.sealed_ground_truth.evaluator_token()
    before = fixture.sealed_ground_truth.open(token, purpose="evaluator")
    commitment = fixture.public.commitment
    source = MCIArmInput(
        fixture.public, initial_theory(), fixture.public.hypotheses,
        {"passive_observation": "mid"},
    )
    _, batch, _, harness, receipt = start_selected_epoch(db, source)
    reference = resolve_outcome(
        db, harness, receipt, episode_id="episode-1", outcome=1, logical_time=10
    )
    MCIOutcomeAdapter(CanonicalEvidenceBridge(db)).revise(
        source.theory, batch.working, batch.prediction_set, receipt, reference,
        epoch=1, logical_time=20,
    )
    after = fixture.sealed_ground_truth.open(token, purpose="evaluator")
    assert after == before
    assert fixture.public.commitment == commitment
