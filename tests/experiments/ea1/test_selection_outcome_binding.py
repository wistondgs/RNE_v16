from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest

from runtime.experiments.ea1.budget import EpistemicBudget
from runtime.experiments.ea1.canonical import stable_id
from runtime.experiments.ea1.contracts import (
    Arm,
    CanonicalOutcomeReference,
    ExperimentProposal,
    Producer,
    ScenarioFamily,
    TheoryState,
)
from runtime.experiments.ea1.harness import (
    EA1_EXECUTION_AUTHORIZATION_FIELD,
    CanonicalOutcomeResolver,
    ExecutionAuthorization,
    NeutralExperimentHarness,
)
from runtime.experiments.ea1.ledger import ExperimentLedger, StorageLedgerBackend
from runtime.experiments.ea1.scenarios import make_smoke_fixture
from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.experience import (
    ExperienceIntegrityError,
    outcome_witness_from_event,
)
from runtime.organism.life_transition import DynamicLifeChain, LifeTransition
from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.canonical_outcomes import (
    ACTING_OWNER,
    _issue_canonical_outcome_authority,
)


def _storage(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(root / "ea1-h2.db"),
            postgres_dsn=None,
            artifact_root=root / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _selected(
    db,
    *,
    run_id: str = "run",
    organism_id: str = "organism-A",
    episode_id: str = "episode-A",
    arm: Arm = Arm.EXPERIMENTAL,
    ledger: ExperimentLedger | None = None,
):
    fixture = make_smoke_fixture(ScenarioFamily.S2)
    experiment_ledger = ledger or ExperimentLedger(StorageLedgerBackend(db))
    harness = NeutralExperimentHarness(
        run_id=run_id,
        arm=arm,
        ledger=experiment_ledger,
        budget=EpistemicBudget(),
        scenario_family=ScenarioFamily.S2.value,
    )
    theory = TheoryState("theory-1", 1, 0.49, 0.49, 0.02, "h1")
    action = fixture.public.actions[0]
    proposal = ExperimentProposal(
        "proposal-1", 1, action.action_id, "predictions", 0.2, 0.1, Producer.ORGANISM
    )
    harness.register_theory(theory)
    harness.register_proposals(1, (proposal,), fixture.public.actions)
    receipt, authorization = harness.select(
        1,
        proposal,
        action,
        selector="h2-test",
        organism_id=organism_id,
        episode_id=episode_id,
    )
    return harness, experiment_ledger, receipt, authorization, action


def _commit_f1a(
    db,
    *,
    authorization: ExecutionAuthorization,
    run_id: str,
    organism_id: str,
    episode_id: str,
    action_id: str,
    logical_time: int = 12,
    include_binding: bool = True,
) -> LifeTransition:
    before = OrganismDynamicState.create(
        organism_id=organism_id,
        lineage_id=f"lineage-{organism_id}",
        run_id=run_id,
        episode_id=episode_id,
        life_step=0,
        logical_time=logical_time,
        previous_state_hash=None,
        world={},
        regime={},
        organism={},
        memory={},
        neural={},
        policy={},
        resources={},
        homeostasis={},
    )
    after = OrganismDynamicState.create(
        organism_id=organism_id,
        lineage_id=f"lineage-{organism_id}",
        run_id=run_id,
        episode_id=episode_id,
        life_step=1,
        logical_time=logical_time + 1,
        previous_state_hash=before.state_hash,
        world={"ea1_binary_outcome": 1},
        regime={},
        organism={},
        memory={},
        neural={},
        policy={},
        resources={},
        homeostasis={},
    )
    facts = {
        "organism_id": organism_id,
        "run_id": run_id,
        "episode_id": episode_id,
        "scenario": "ea1-h2-dev",
        "regime": "dev",
        "main_variable": "binary_outcome",
        "causal_status": "",
        "intervention": action_id,
        "viability_margin": 0.8,
        "ioc": 0.7,
        "risk": 0.25,
        "reward": 1.0,
        "action": "act",
        "certified": False,
        "closure_passed": True,
        "viability_delta": 0.0,
    }
    authoritative = (
        {EA1_EXECUTION_AUTHORIZATION_FIELD: authorization.to_payload()}
        if include_binding
        else {}
    )
    transition = DynamicLifeChain(
        organism_id=organism_id,
        lineage_id=f"lineage-{organism_id}",
        run_id=run_id,
    ).commit(
        state_before=before,
        state_after=after,
        trace_group_id=f"trace-{episode_id}",
        action_proposals=(),
        authoritative_decision=authoritative,
        committed_intervention={"intervention": action_id},
        external_input=None,
        factual_outcome={
            "world_state_hash": after.state_hash,
            "ea1_binary_outcome": 1,
            "experience_facts": facts,
        },
        counterfactual_evidence={},
        certificate={},
        reward={"reward": 1.0},
        memory_delta={},
        neural_state_delta={},
        policy_delta={},
        resource_delta={},
        viability_delta={},
        regime_before={},
        regime_after={},
        rollback_refuge_result={},
        outcome_authority=_issue_canonical_outcome_authority(
            storage=db, owner=ACTING_OWNER
        ),
    )
    assert transition.status == "committed"
    return transition


def _reference_for(
    db, receipt, transition: LifeTransition
) -> CanonicalOutcomeReference:
    event = next(
        event
        for event in db.list_events(
            run_id=receipt.run_id,
            event_types=["organism.life_transition.committed"],
            limit=10000,
        )
        if LifeTransition.from_dict(event.payload).transition_id
        == transition.transition_id
    )
    witness = outcome_witness_from_event(event)
    identity = {
        "selection_receipt_id": receipt.receipt_id,
        "execution_id": receipt.execution_id,
        "witness_id": witness.witness_id,
    }
    return CanonicalOutcomeReference(
        stable_id("outref", identity),
        receipt.receipt_id,
        witness.source_event_type,
        witness.source_record_id,
        witness.witness_id,
        witness.committed_intervention,
        witness.outcome_hash,
        receipt.execution_id,
        receipt.authorization_id,
        witness.organism_id,
        witness.episode_id,
        transition.state_after.logical_time,
    )


def test_t1_t2_persisted_receipt_is_required_and_tampering_fails(tmp_path: Path) -> None:
    db = _storage(tmp_path / "receipt")
    _, ledger, receipt, authorization, action = _selected(db)
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
    )
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    with pytest.raises(ExperienceIntegrityError, match="persisted_selection"):
        resolver.validate(replace(receipt, selector="tampered"), reference)

    _, _, unpersisted, _, _ = _selected(
        db, run_id="unpersisted-run", ledger=ExperimentLedger()
    )
    with pytest.raises(ExperienceIntegrityError, match="not_persisted"):
        resolver.validate(unpersisted, reference)


def test_t3_valid_post_selection_outcome_is_accepted(tmp_path: Path) -> None:
    db = _storage(tmp_path / "valid")
    harness, ledger, receipt, authorization, action = _selected(db)
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
    )
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    harness.attach_outcome(1, reference, resolver=resolver)
    assert reference.canonical_event_logical_time > receipt.logical_time


@pytest.mark.parametrize(
    ("logical_time", "expected"),
    ((1, "outcome_precedes_selection"), (12, "execution_authorization_mismatch")),
)
def test_t4_preselection_canonical_outcome_is_rejected(
    tmp_path: Path, logical_time: int, expected: str
) -> None:
    db = _storage(tmp_path / "preselection")
    _, _, preview_receipt, preview_authorization, action = _selected(
        db, ledger=ExperimentLedger()
    )
    transition = _commit_f1a(
        db,
        authorization=preview_authorization,
        run_id=preview_receipt.run_id,
        organism_id=preview_receipt.organism_id,
        episode_id=preview_receipt.episode_id,
        action_id=action.action_id,
        logical_time=logical_time,
    )
    _, ledger, receipt, authorization, selected_action = _selected(db)
    assert receipt.receipt_id == preview_receipt.receipt_id
    assert receipt.execution_id == preview_receipt.execution_id
    assert receipt.authorization_id != preview_receipt.authorization_id
    assert authorization.authorization_token != preview_authorization.authorization_token
    assert selected_action == action
    reference = _reference_for(db, receipt, transition)
    with pytest.raises(ExperienceIntegrityError, match=expected):
        CanonicalOutcomeResolver(db, ledger).validate(receipt, reference)


@pytest.mark.parametrize(
    ("organism_id", "episode_id", "action_mode", "expected"),
    (
        ("organism-A", "episode-B", "selected", "outcome_episode_mismatch"),
        ("organism-A", "episode-A", "other", "outcome_action_mismatch"),
        ("organism-B", "episode-A", "selected", "outcome_organism_mismatch"),
    ),
)
def test_t5_t6_t7_cross_identity_outcomes_are_rejected(
    tmp_path: Path,
    organism_id: str,
    episode_id: str,
    action_mode: str,
    expected: str,
) -> None:
    db = _storage(tmp_path / expected)
    _, ledger, receipt, authorization, action = _selected(db)
    other_action = make_smoke_fixture(ScenarioFamily.S2).public.actions[1]
    action_id = action.action_id if action_mode == "selected" else other_action.action_id
    transition = _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=organism_id,
        episode_id=episode_id,
        action_id=action_id,
    )
    reference = _reference_for(db, receipt, transition)
    with pytest.raises(ExperienceIntegrityError, match=expected):
        CanonicalOutcomeResolver(db, ledger).validate(receipt, reference)


def test_t8_t9_t10_reference_identity_is_recomputed(tmp_path: Path) -> None:
    db = _storage(tmp_path / "reference")
    _, ledger, receipt, authorization, action = _selected(db)
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
    )
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)

    with pytest.raises(ExperienceIntegrityError, match="reference_id_mismatch"):
        resolver.validate(receipt, replace(reference, reference_id="forged-reference"))

    _, _, other_receipt, _, _ = _selected(
        db, run_id="other-selection", ledger=ExperimentLedger()
    )
    other_selection_reference = replace(
        reference,
        selection_receipt_id=other_receipt.receipt_id,
        reference_id=stable_id(
            "outref",
            {
                "selection_receipt_id": other_receipt.receipt_id,
                "execution_id": receipt.execution_id,
                "witness_id": reference.witness_id,
            },
        ),
    )
    with pytest.raises(ExperienceIntegrityError, match="selection_mismatch"):
        resolver.validate(receipt, other_selection_reference)

    other_transition = _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id="organism-other-witness",
        episode_id="episode-other-witness",
        action_id=action.action_id,
    )
    other_event = next(
        event
        for event in db.list_events(
            run_id=receipt.run_id,
            event_types=["organism.life_transition.committed"],
            limit=10000,
        )
        if LifeTransition.from_dict(event.payload).transition_id
        == other_transition.transition_id
    )
    other_witness_id = outcome_witness_from_event(other_event).witness_id
    other_witness_reference = replace(
        reference,
        witness_id=other_witness_id,
        reference_id=stable_id(
            "outref",
            {
                "selection_receipt_id": receipt.receipt_id,
                "execution_id": receipt.execution_id,
                "witness_id": other_witness_id,
            },
        ),
    )
    with pytest.raises(ExperienceIntegrityError, match="witness_mismatch"):
        resolver.validate(receipt, other_witness_reference)


def test_t11_missing_execution_binding_is_rejected(tmp_path: Path) -> None:
    db = _storage(tmp_path / "missing-binding")
    _, ledger, receipt, authorization, action = _selected(db)
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
        include_binding=False,
    )
    with pytest.raises(ExperienceIntegrityError, match="execution_binding_missing"):
        CanonicalOutcomeResolver(db, ledger).resolve(receipt)


def test_t12_t13_binding_and_temporal_relation_survive_reload(tmp_path: Path) -> None:
    db = _storage(tmp_path / "reload")
    _, ledger, receipt, authorization, action = _selected(db)
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
    )
    reference = CanonicalOutcomeResolver(db, ledger).resolve(receipt)

    reloaded_ledger = ExperimentLedger(StorageLedgerBackend(db))
    reloaded_resolver = CanonicalOutcomeResolver(db, reloaded_ledger)
    assert reloaded_resolver.resolve(receipt) == reference
    reloaded_resolver.validate(receipt, reference)

    # H2 deliberately does not persist consumption; H3 must close exactly-once use.
    second_reload = CanonicalOutcomeResolver(
        db, ExperimentLedger(StorageLedgerBackend(db))
    )
    second_reload.validate(receipt, reference)


def test_t14_t15_raw_and_simulated_outputs_remain_non_authoritative(
    tmp_path: Path,
) -> None:
    db = _storage(tmp_path / "non-authoritative")
    _, ledger, receipt, _, _ = _selected(db)
    resolver = CanonicalOutcomeResolver(db, ledger)
    for value in (
        {"outcome": 1},
        {"evidence_type": "SIMULATED/MODEL_BASED", "success_probability": 1.0},
    ):
        with pytest.raises(
            ExperienceIntegrityError, match="canonical_outcome_reference_required"
        ):
            resolver.validate(receipt, value)  # type: ignore[arg-type]


def test_t16_f1a_witness_content_tampering_remains_rejected(tmp_path: Path) -> None:
    db = _storage(tmp_path / "witness-tamper")
    _, ledger, receipt, authorization, action = _selected(db)
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
    )
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    with pytest.raises(ExperienceIntegrityError, match="outcome_mismatch"):
        resolver.validate(receipt, replace(reference, outcome_hash="tampered"))


@pytest.mark.parametrize(
    "arm", (Arm.EXPERIMENTAL, Arm.C1_GREEDY, Arm.C2_RANDOM, Arm.C5_ORACLE)
)
def test_t17_binding_contract_is_arm_neutral(tmp_path: Path, arm: Arm) -> None:
    root = tmp_path / arm.value
    db = _storage(root)
    run_id = f"run-{arm.value}"
    organism_id = f"organism-{arm.value}"
    episode_id = f"episode-{arm.value}"
    harness, ledger, receipt, authorization, action = _selected(
        db,
        run_id=run_id,
        organism_id=organism_id,
        episode_id=episode_id,
        arm=arm,
    )
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=run_id,
        organism_id=organism_id,
        episode_id=episode_id,
        action_id=action.action_id,
    )
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    harness.attach_outcome(1, reference, resolver=resolver)


def test_selection_exposes_execution_identity_but_no_future_outcome_identity() -> None:
    from runtime.experiments.ea1.contracts import ExperimentSelectionReceipt

    names = {field.name for field in fields(ExperimentSelectionReceipt)}
    assert {"execution_id", "authorization_id", "organism_id", "episode_id"} <= names
    assert not names & {
        "witness_id",
        "canonical_event_id",
        "canonical_event_logical_time",
        "outcome_hash",
        "outcome",
    }
