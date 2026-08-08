from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

from runtime.life import AutonomyDecision, LifeKernel, LifeKernelConfig
from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.experience import ExperienceStore, build_experience, outcome_witness_from_event
from runtime.organism.life_transition import DynamicLifeChain, LifeTransition
from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.canonical_outcomes import (
    ACTING_OUTCOME_EVENT,
    ACTING_OWNER,
    ReservedCanonicalOutcomeError,
    _issue_canonical_outcome_authority,
)
from runtime.storage.records import StoredEvent
from runtime.world import ScenarioEpisodeRunner


pytestmark = pytest.mark.requires_postgres


def _test_dsn() -> str:
    dsn = os.environ.get("RNFE_CG_POSTGRES_TEST_DSN", "").strip()
    if not dsn:
        pytest.skip("RNFE_CG_POSTGRES_TEST_DSN isolated database is required")
    return dsn


def _truncate_public_tables(dsn: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        names = [row[0] for row in cur.fetchall()]
        if names:
            cur.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(name) for name in names)
                )
            )
        conn.commit()


@pytest.fixture
def pg_storage(tmp_path: Path):
    dsn = _test_dsn()
    storage = StorageFactory.create_facade(
        StorageConfig(
            mode="postgres",
            sqlite_db_path=str(tmp_path / "unused.db"),
            postgres_dsn=dsn,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=True,
            strict_dual_write=True,
        )
    )
    _truncate_public_tables(dsn)
    try:
        yield storage
    finally:
        storage.close()
        _truncate_public_tables(dsn)


def _states(*, episode: str = "episode", previous: str | None = None, offset: int = 0):
    before = OrganismDynamicState.create(
        organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run",
        episode_id=episode, life_step=offset, logical_time=offset * 2 + 1,
        previous_state_hash=previous, world={}, regime={}, organism={}, memory={},
        neural={}, policy={}, resources={}, homeostasis={},
    )
    after = OrganismDynamicState.create(
        organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run",
        episode_id=episode, life_step=offset + 1, logical_time=offset * 2 + 2,
        previous_state_hash=before.state_hash, world={"episode": episode}, regime={},
        organism={}, memory={}, neural={}, policy={}, resources={}, homeostasis={},
    )
    return before, after


def _facts(*, episode: str = "episode", risk: float = 0.9):
    return {
        "organism_id": "pg-organism", "run_id": "pg-run", "episode_id": episode,
        "scenario": "thermal", "regime": "alarm", "main_variable": "temp",
        "causal_status": "", "intervention": "cooling_on",
        "viability_margin": 0.1, "ioc": 0.2, "risk": risk, "reward": -0.7,
        "action": "act", "certified": False, "closure_passed": False,
        "viability_delta": -0.4,
    }


def _commit(chain, authority, *, facts, before=None, after=None, trace="pg-trace"):
    if before is None or after is None:
        before, after = _states(episode=facts["episode_id"])
    return chain.commit(
        state_before=before, state_after=after, trace_group_id=trace,
        action_proposals=(), authoritative_decision={},
        committed_intervention={"intervention": "cooling_on"}, external_input=None,
        factual_outcome={"world_state_hash": "world", "experience_facts": facts},
        counterfactual_evidence={}, certificate={}, reward={"reward": facts["reward"]},
        memory_delta={}, neural_state_delta={}, policy_delta={}, resource_delta={},
        viability_delta={}, regime_before={}, regime_after={}, rollback_refuge_result={},
        outcome_authority=authority,
    )


def test_p1_acting_positive_path(pg_storage, monkeypatch) -> None:
    monkeypatch.setenv("RNFE_EXPERIENCE", "1")
    runner = ScenarioEpisodeRunner(
        storage=pg_storage, run_id="pg-p1", scenario="thermal_homeostasis"
    )
    runner.set_organism_id("pg-p1-organism")

    result = runner.run_episode(external_input=0.04)

    assert result["life_transition"]["status"] == "committed"
    assert result["experience"]["situation_key"]
    wisdom = ExperienceStore(storage=pg_storage).wisdom(
        organism_id="pg-p1-organism", situation=result["experience"]["situation_key"]
    )
    assert wisdom.n == 1
    assert wisdom.witness_verified_n == 1


def test_p2_nonacting_positive_path(pg_storage, monkeypatch) -> None:
    monkeypatch.setenv("RNFE_EXPERIENCE", "1")
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="pg-p2", organism_id="pg-p2-organism",
            scenarios=("thermal_homeostasis",), restore=False,
            enable_msrc=False, enable_operational_conjunction=False,
        ),
        storage=pg_storage,
    )
    monkeypatch.setattr(
        kernel.supervisor,
        "decide",
        lambda **_: AutonomyDecision(
            action="sleep", mode="conservative", reason="pg-p2",
            scenario="thermal_homeostasis",
        ),
    )

    result = kernel.step(external_input=0.05)
    records = ExperienceStore(storage=pg_storage).recall(organism_id=kernel.organism_id)

    assert result.decision.action == "sleep"
    assert len(records) == 1
    wisdom = ExperienceStore(storage=pg_storage).wisdom(
        organism_id=kernel.organism_id, situation=records[0]["situation_key"]
    )
    assert wisdom.n == 1
    assert wisdom.witness_verified_n == 1


def test_p3_exact_replay_is_idempotent(pg_storage) -> None:
    authority = _issue_canonical_outcome_authority(storage=pg_storage, owner=ACTING_OWNER)
    first = _commit(
        DynamicLifeChain(organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run"),
        authority, facts=_facts(),
    )
    replay = _commit(
        DynamicLifeChain(organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run"),
        authority, facts=_facts(),
    )

    assert first.status == replay.status == "committed"
    assert authority.observations["duplicate_exact"] == 1
    assert len(pg_storage.list_events(run_id="pg-run", event_types=[ACTING_OUTCOME_EVENT])) == 1


def test_p4_divergent_duplicate_fails_closed(pg_storage) -> None:
    authority = _issue_canonical_outcome_authority(storage=pg_storage, owner=ACTING_OWNER)
    first = _commit(
        DynamicLifeChain(organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run"),
        authority, facts=_facts(),
    )
    divergent = _commit(
        DynamicLifeChain(organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run"),
        authority, facts=_facts(risk=0.1),
    )

    assert first.status == "committed"
    assert divergent.status == "incomplete"
    assert authority.observations["duplicate_divergent"] == 1
    assert len(pg_storage.list_events(run_id="pg-run", event_types=[ACTING_OUTCOME_EVENT])) == 1


def test_p5_chain_continuation_survives_postgres_reread(pg_storage, monkeypatch) -> None:
    monkeypatch.setenv("RNFE_EXPERIENCE", "0")
    first_runner = ScenarioEpisodeRunner(
        storage=pg_storage, run_id="pg-p5", scenario="thermal_homeostasis"
    )
    first_runner.set_organism_id("pg-p5-organism")
    first = first_runner.run_episode(external_input=0.04)
    checkpoint = first_runner.export_neural_state()

    resumed = ScenarioEpisodeRunner(
        storage=pg_storage, run_id="pg-p5", scenario="thermal_homeostasis",
        organism_state=first_runner.organism_state, lineage=first_runner.lineage,
    )
    resumed.set_organism_id("pg-p5-organism")
    resumed.restore_neural_state(checkpoint)
    second = resumed.run_episode(external_input=0.14)
    rows = pg_storage.list_events(
        run_id="pg-p5", event_types=[ACTING_OUTCOME_EVENT], limit=10
    )
    transitions = [LifeTransition.from_dict(row.payload) for row in rows]

    assert [item.transition_index for item in transitions] == [1, 2]
    assert transitions[1].previous_transition_id == transitions[0].transition_id
    assert transitions[1].previous_transition_hash == transitions[0].transition_hash
    assert second["life_transition"]["transition_index"] == 2


@pytest.mark.parametrize(
    ("event_type", "source"),
    [(ACTING_OUTCOME_EVENT, ACTING_OWNER), ("life.sleep", "life_kernel")],
)
def test_p6_p7_generic_reserved_write_and_source_imitation_are_rejected(
    pg_storage, event_type: str, source: str
) -> None:
    with pytest.raises(ReservedCanonicalOutcomeError):
        pg_storage.append_event(
            event_type=event_type, run_id="pg-generic", source=source, payload={}
        )
    with pytest.raises(ReservedCanonicalOutcomeError):
        pg_storage.backend.append_event(
            StoredEvent(
                event_type=event_type, run_id="pg-generic", source=source, payload={}
            )
        )
    assert pg_storage.list_events(
        run_id="pg-generic", event_types=[event_type]
    ) == []


def test_p8_missing_anchor_revokes_experience(pg_storage) -> None:
    authority = _issue_canonical_outcome_authority(storage=pg_storage, owner=ACTING_OWNER)
    transition = _commit(
        DynamicLifeChain(organism_id="pg-organism", lineage_id="pg-lineage", run_id="pg-run"),
        authority, facts=_facts(),
    )
    event = pg_storage.list_events(
        run_id="pg-run", event_types=[ACTING_OUTCOME_EVENT]
    )[0]
    witness = outcome_witness_from_event(event)
    experience = build_experience(
        organism_id="pg-organism", run_id="pg-run", episode_id="episode",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="cooling_on", viability_margin=0.1, ioc=0.2, risk=0.9,
        reward=-0.7, action="act", outcome_witness=witness, certified=False,
        closure_passed=False, viability_delta=-0.4,
    )
    store = ExperienceStore(storage=pg_storage)
    assert transition.status == "committed"
    assert store.record(experience) is True
    assert store.wisdom(organism_id="pg-organism", situation=experience.situation_key).n == 1

    with psycopg.connect(_test_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ledger_events WHERE run_id = %s AND event_type = %s",
            ("pg-run", ACTING_OUTCOME_EVENT),
        )
        conn.commit()

    wisdom = store.wisdom(
        organism_id="pg-organism", situation=experience.situation_key
    )
    assert wisdom.n == 0
    assert wisdom.rejected_unresolved_witness == 1
