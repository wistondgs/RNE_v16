from __future__ import annotations

from pathlib import Path

import pytest

from runtime.life.contracts import AutonomyDecision, VitalSignsSnapshot
from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.experience import ExperienceStore, build_experience, outcome_witness_from_event
from runtime.organism.life_transition import DynamicLifeChain
from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.canonical_outcomes import (
    ACTING_OUTCOME_EVENT,
    ACTING_OWNER,
    NONACTING_OWNER,
    CanonicalOutcomeAuthority,
    ReservedCanonicalOutcomeError,
    _issue_canonical_outcome_authority,
)
from runtime.storage.records import StoredEvent


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "authority.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _states(*, risk: float = 0.9):
    before = OrganismDynamicState.create(
        organism_id="organism", lineage_id="lineage", run_id="run",
        episode_id="episode", life_step=0, logical_time=1,
        previous_state_hash=None, world={}, regime={}, organism={}, memory={},
        neural={}, policy={}, resources={}, homeostasis={},
    )
    after = OrganismDynamicState.create(
        organism_id="organism", lineage_id="lineage", run_id="run",
        episode_id="episode", life_step=1, logical_time=2,
        previous_state_hash=before.state_hash, world={"risk": risk}, regime={},
        organism={}, memory={}, neural={}, policy={}, resources={}, homeostasis={},
    )
    return before, after


def _facts(*, risk: float = 0.9):
    return {
        "organism_id": "organism", "run_id": "run", "episode_id": "episode",
        "scenario": "thermal", "regime": "alarm", "main_variable": "temp",
        "causal_status": "", "intervention": "cooling_on",
        "viability_margin": 0.1, "ioc": 0.2, "risk": risk, "reward": -0.7,
        "action": "act", "certified": False, "closure_passed": False,
        "viability_delta": -0.4,
    }


def _commit(chain, *, authority, facts):
    before, after = _states()
    return chain.commit(
        state_before=before, state_after=after, trace_group_id="trace",
        action_proposals=(), authoritative_decision={},
        committed_intervention={"intervention": "cooling_on"}, external_input=None,
        factual_outcome={"world_state_hash": "world", "experience_facts": facts},
        counterfactual_evidence={}, certificate={}, reward={"reward": facts["reward"]},
        memory_delta={}, neural_state_delta={}, policy_delta={}, resource_delta={},
        viability_delta={}, regime_before={}, regime_after={}, rollback_refuge_result={},
        outcome_authority=authority,
    )


@pytest.mark.parametrize(
    ("event_type", "source"),
    [
        (ACTING_OUTCOME_EVENT, ACTING_OWNER),
        ("life.sleep", NONACTING_OWNER),
    ],
)
def test_generic_facade_and_backend_reject_reserved_outcomes(
    tmp_path: Path, event_type: str, source: str
) -> None:
    storage = _storage(tmp_path)
    with pytest.raises(ReservedCanonicalOutcomeError):
        storage.append_event(
            event_type=event_type, run_id="run", source=source, payload={}
        )
    with pytest.raises(ReservedCanonicalOutcomeError):
        storage.backend.append_event(
            StoredEvent(event_type=event_type, run_id="run", source=source, payload={})
        )
    assert storage.list_events(run_id="run", event_types=[event_type]) == []


def test_source_string_and_public_constructor_cannot_grant_authority(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    with pytest.raises(ReservedCanonicalOutcomeError):
        storage.append_event(
            event_type=ACTING_OUTCOME_EVENT,
            run_id="run",
            source=ACTING_OWNER,
            payload={"source": ACTING_OWNER},
        )
    with pytest.raises(ValueError, match="issuer_required"):
        CanonicalOutcomeAuthority(storage=storage, owner=ACTING_OWNER, issuer=object())


def test_postgres_generic_writer_rejects_before_database_io() -> None:
    from runtime.storage.backends.postgres_store import PostgresStorageBackend

    backend = object.__new__(PostgresStorageBackend)
    event = StoredEvent(
        event_type=ACTING_OUTCOME_EVENT,
        run_id="run",
        source=ACTING_OWNER,
        payload={},
    )
    with pytest.raises(ReservedCanonicalOutcomeError):
        backend.append_event(event)
    with pytest.raises(ReservedCanonicalOutcomeError):
        backend.append_canonical_outcome(event, object())


def test_independent_chain_without_capability_is_non_authoritative(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    transition = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=None,
        facts=_facts(),
    )
    assert transition.status == "incomplete"
    assert transition.reason_code == "life_transition_persistence_failed"
    assert storage.list_events(
        run_id="run", event_types=[ACTING_OUTCOME_EVENT]
    ) == []


def test_canonical_acting_path_reaches_wisdom(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    authority = _issue_canonical_outcome_authority(storage=storage, owner=ACTING_OWNER)
    transition = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=authority,
        facts=_facts(),
    )
    assert transition.status == "committed"
    event = storage.list_events(
        run_id="run", event_types=[ACTING_OUTCOME_EVENT]
    )[0]
    witness = outcome_witness_from_event(event)
    experience = build_experience(
        organism_id="organism", run_id="run", episode_id="episode",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="cooling_on", viability_margin=0.1, ioc=0.2, risk=0.9,
        reward=-0.7, action="act", outcome_witness=witness, certified=False,
        closure_passed=False, viability_delta=-0.4,
    )
    store = ExperienceStore(storage=storage)
    assert store.record(experience) is True
    wisdom = store.wisdom(organism_id="organism", situation=experience.situation_key)
    assert wisdom.n == 1
    assert wisdom.avoid == "cooling_on"


def test_canonical_nonacting_path_reaches_wisdom(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    authority = _issue_canonical_outcome_authority(storage=storage, owner=NONACTING_OWNER)
    decision = AutonomyDecision(action="sleep", mode="recovery", reason="review")
    vitals = VitalSignsSnapshot(
        run_id="run", episode_count=1, mode="recovery", viability_margin=0.2,
        continuity_score=0.4, ioc_proxy=0.2, risk_score=0.8,
        memory_purity=0.7, cognitive_quality=0.4, resource_pressure=0.5,
        recovery_debt=0.2, accumulated_drift=0.1, reversible=True,
        identity_continuity=1.0, certified=False,
    )
    result = authority.commit_nonacting_decision(
        decision=decision, vitals=vitals, checkpoint_artifact_id="checkpoint",
        organism_id="organism", run_id="run", episode_id="life-sleep-1",
        step_index=1, scenario="thermal", main_variable="temp",
    )
    witness = outcome_witness_from_event(result.event)
    experience = build_experience(
        organism_id="organism", run_id="run", episode_id="life-sleep-1",
        scenario="thermal", regime="rest", main_variable="temp", causal_status="",
        intervention="", viability_margin=0.2, ioc=0.2, risk=0.8, reward=0.0,
        action="sleep", outcome_witness=witness, certified=False,
        closure_passed=False, viability_delta=0.0,
    )
    store = ExperienceStore(storage=storage)
    assert store.record(experience) is True
    assert store.wisdom(organism_id="organism", situation=experience.situation_key).n == 1


def test_exact_replay_is_idempotent_and_divergent_identity_fails_closed(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    authority = _issue_canonical_outcome_authority(storage=storage, owner=ACTING_OWNER)
    first = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=authority, facts=_facts(),
    )
    exact = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=authority, facts=_facts(),
    )
    divergent = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=authority, facts=_facts(risk=0.1),
    )
    assert first.status == "committed"
    assert exact.status == "committed"
    assert divergent.status == "incomplete"
    assert authority.observations["duplicate_exact"] == 1
    assert authority.observations["duplicate_divergent"] == 1
    assert len(storage.list_events(run_id="run", event_types=[ACTING_OUTCOME_EVENT])) == 1


def test_second_independent_genesis_is_not_canonical(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    authority = _issue_canonical_outcome_authority(storage=storage, owner=ACTING_OWNER)
    first = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=authority, facts=_facts(),
    )
    before, after = _states()
    alternate = DynamicLifeChain(
        organism_id="organism", lineage_id="lineage", run_id="run"
    ).commit(
        state_before=before, state_after=after, trace_group_id="alternate-trace",
        action_proposals=(), authoritative_decision={},
        committed_intervention={"intervention": "cooling_on"}, external_input=None,
        factual_outcome={"world_state_hash": "other", "experience_facts": _facts()},
        counterfactual_evidence={}, certificate={}, reward={}, memory_delta={},
        neural_state_delta={}, policy_delta={}, resource_delta={}, viability_delta={},
        regime_before={}, regime_after={}, rollback_refuge_result={},
        outcome_authority=authority,
    )
    assert first.status == "committed"
    assert alternate.status == "incomplete"
    assert len(storage.list_events(run_id="run", event_types=[ACTING_OUTCOME_EVENT])) == 1


def test_saturated_lookup_window_cannot_create_new_genesis(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _storage(tmp_path)
    authority = _issue_canonical_outcome_authority(storage=storage, owner=ACTING_OWNER)
    unresolved = StoredEvent(
        event_type=ACTING_OUTCOME_EVENT,
        run_id="other-run",
        source=ACTING_OWNER,
        payload={"malformed": True},
    )
    monkeypatch.setattr(storage, "list_events", lambda **_kwargs: [unresolved] * 5000)

    transition = _commit(
        DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run"),
        authority=authority,
        facts=_facts(),
    )

    assert transition.status == "incomplete"
    assert authority.observations["authority_unavailable"] == 1
