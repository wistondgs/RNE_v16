from __future__ import annotations

from pathlib import Path

import pytest

from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.life_transition import DynamicLifeChain
from runtime.storage import StorageConfig, StorageFactory
from runtime.world import ScenarioEpisodeRunner


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "dynamic-life.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def test_dynamic_state_hash_fails_closed_on_tampering() -> None:
    state = OrganismDynamicState.create(
        organism_id="organism",
        lineage_id="lineage",
        run_id="run",
        episode_id="episode",
        life_step=0,
        logical_time=0,
        previous_state_hash=None,
        world={"world_state_hash": "world"},
        regime={"regime_id": "regime"},
        organism={"organism_state_id": "state"},
        memory={},
        neural={},
        policy={},
        resources={"cpu": {"value": None, "measurement_status": "unmeasured"}},
        homeostasis={},
    )
    payload = state.to_dict()
    payload["world"]["world_state_hash"] = "tampered"
    with pytest.raises(ValueError, match="state_hash_mismatch"):
        OrganismDynamicState.from_dict(payload)


def test_checkpoint_continues_chain_across_new_run_and_rejects_foreign_identity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path)
    first_runner = ScenarioEpisodeRunner(
        storage=storage,
        run_id="run-before",
        scenario="thermal_homeostasis",
    )
    first_runner.set_organism_id("organism-stable")
    first = first_runner.run_episode(external_input=0.04)
    checkpoint = first_runner.export_neural_state()

    resumed = ScenarioEpisodeRunner(
        storage=storage,
        run_id="run-after",
        scenario="thermal_homeostasis",
        organism_state=first_runner.organism_state,
        lineage=first_runner.lineage,
    )
    resumed.set_organism_id("organism-stable")
    assert resumed.restore_neural_state(checkpoint) >= 1
    second = resumed.run_episode(external_input=0.14)
    assert second["life_transition"]["transition_index"] == 2
    assert (
        second["life_transition"]["previous_transition_hash"]
        == first["life_transition"]["transition_hash"]
    )
    assert second["dynamic_state"]["run_id"] == "run-after"

    foreign = ScenarioEpisodeRunner(
        storage=storage,
        run_id="run-foreign",
        scenario="thermal_homeostasis",
        organism_state=first_runner.organism_state,
        lineage=first_runner.lineage,
    )
    foreign.set_organism_id("other-organism")
    with pytest.raises(ValueError, match="checkpoint_organism_mismatch"):
        foreign.restore_neural_state(checkpoint)
    storage.close()


def test_legacy_n3_checkpoint_opens_explicit_chain_epoch(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    runner = ScenarioEpisodeRunner(
        storage=storage, run_id="legacy-run", scenario="thermal_homeostasis"
    )
    runner.set_organism_id("legacy-organism")
    modern = runner.export_neural_state()
    runner.restore_neural_state(modern["n3_temporal_state"])
    chain = runner.export_neural_state()["dynamic_chain"]
    assert chain["chain_epoch"] == 2
    assert chain["restore_reason"] == "legacy_checkpoint_without_dynamic_chain"
    storage.close()


def test_unpersisted_transition_is_incomplete_and_does_not_advance_chain() -> None:
    class BrokenStorage:
        def append_event(self, **_kwargs):
            raise OSError("ledger unavailable")

    def state(logical_time: int, previous: str | None) -> OrganismDynamicState:
        return OrganismDynamicState.create(
            organism_id="organism",
            lineage_id="lineage",
            run_id="run",
            episode_id="episode",
            life_step=logical_time,
            logical_time=logical_time,
            previous_state_hash=previous,
            world={"step": logical_time},
            regime={"regime_id": "regime"},
            organism={}, memory={}, neural={}, policy={}, resources={}, homeostasis={},
        )

    chain = DynamicLifeChain(organism_id="organism", lineage_id="lineage", run_id="run")
    before = state(0, None)
    after = state(1, before.state_hash)
    transition = chain.commit(
        state_before=before,
        state_after=after,
        trace_group_id="trace",
        action_proposals=(),
        authoritative_decision={},
        committed_intervention={},
        external_input=None,
        factual_outcome={},
        counterfactual_evidence={},
        certificate={},
        reward={},
        memory_delta={},
        neural_state_delta={},
        policy_delta={},
        resource_delta={},
        viability_delta={},
        regime_before={},
        regime_after={},
        rollback_refuge_result={},
        storage=BrokenStorage(),
    )
    assert transition.status == "incomplete"
    assert transition.reason_code == "life_transition_persistence_failed"
    assert chain.transition_index == 0
    assert chain.last_state is None
