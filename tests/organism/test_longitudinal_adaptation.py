from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from runtime.organism.adaptive_state import (
    ALLOWED_ADAPTATION_ACTIONS,
    AdaptationPlanner,
    AdaptiveStateStore,
    OrganAdaptiveState,
)
from runtime.organism.life_transition import LifeTransition
from runtime.organism.trajectory_window import TrajectoryWindowBuilder
from runtime.storage import StorageConfig, StorageFactory
from runtime.world import ScenarioEpisodeRunner


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "longitudinal.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts-longitudinal",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _runner_with_two_episodes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path)
    runner = ScenarioEpisodeRunner(
        storage=storage, run_id="run-longitudinal", scenario="thermal_homeostasis"
    )
    runner.set_organism_id("organism-longitudinal")
    runner.run_episode(external_input=0.04)
    runner.run_episode(external_input=0.14)
    return storage, runner


def test_window_preserves_order_identity_and_chain_hashes(tmp_path: Path, monkeypatch) -> None:
    storage, runner = _runner_with_two_episodes(tmp_path, monkeypatch)
    window = runner.build_dynamic_trajectory_window(size=2)
    assert window.closed is True
    assert window.start_transition_index == 1
    assert window.end_transition_index == 2
    assert [item.transition_index for item in window.transitions] == [1, 2]
    assert not hasattr(TrajectoryWindowBuilder, "shuffle")
    assert not hasattr(TrajectoryWindowBuilder, "random_split")

    damaged = replace(
        window.transitions[1], previous_transition_hash="not-the-previous-hash"
    )
    with pytest.raises(ValueError, match="chain_hash_gap"):
        TrajectoryWindowBuilder(
            (window.transitions[0], damaged), chain_epoch=window.chain_epoch
        )
    storage.close()


def test_shadow_replay_uses_fresh_adapters_and_does_not_touch_chain(
    tmp_path: Path, monkeypatch
) -> None:
    storage, runner = _runner_with_two_episodes(tmp_path, monkeypatch)
    before = runner.export_neural_state()["dynamic_chain"]
    replay = runner.replay_dynamic_trajectory(organ_id="N1", size=2)
    after = runner.export_neural_state()["dynamic_chain"]
    assert replay["schema_version"] == "organism-trajectory-replay-v1"
    assert replay["authority_effect"] == "none"
    assert replay["writes_performed"] is False
    assert replay["original_chain_untouched"] is True
    assert before["last_transition_hash"] == after["last_transition_hash"]
    assert before["transition_index"] == after["transition_index"]
    assert len(replay["results"]) == 2
    assert all(row["uncertainty_measurement_status"] == "measured" for row in replay["results"])
    assert all(row["uncertainty_difference"] is not None for row in replay["results"])
    assert all(row["cost_measurement_status"] == "measured" for row in replay["results"])
    assert all("observable_regret" not in row for row in replay["results"])
    assert all("historical_reward" in row for row in replay["results"])
    storage.close()


def test_absent_reward_is_not_counted_as_zero_and_planner_actions_are_closed(
    tmp_path: Path, monkeypatch
) -> None:
    storage, runner = _runner_with_two_episodes(tmp_path, monkeypatch)
    transition = LifeTransition.from_dict(runner.run_episode(external_input=0.04)["life_transition"])
    trace = runner.run_episode(external_input=0.04)["neural_symbiosis_trace"]
    without_reward = replace(transition, reward={})
    adaptive = AdaptiveStateStore(
        organism_id="organism-longitudinal",
        lineage_id=runner.lineage.lineage_id,
    )
    states = adaptive.update(without_reward, trace)
    assert states
    assert all(state.delayed_reward_count == 0 for state in states)
    assert all(state.delayed_reward_mean is None for state in states)

    n1 = next(state for state in states if state.organ_id == "N1")
    assert n1.accepted_count == 0
    assert n1.compared_count >= 1
    assert n1.observed_count >= 1
    assert n1.consumer_acceptance_rate is None
    assert n1.acceptance_denominator == 0

    causal = OrganAdaptiveState(
        organism_id="organism-longitudinal",
        lineage_id=runner.lineage.lineage_id,
        regime_id="homeostatic_cooling",
        organ_id="N4",
        backend_id="reference",
        participation_count=2,
        causal_disagreement_count=2,
        causal_observation_count=2,
    )
    plans = AdaptationPlanner().plan([causal])
    assert plans[0]["allowed_action"] == "quarantine_candidate"
    assert {item["allowed_action"] for item in plans}.issubset(ALLOWED_ADAPTATION_ACTIONS)
    storage.close()


def test_adaptive_receipt_rates_use_only_typed_accept_reject_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    storage, runner = _runner_with_two_episodes(tmp_path, monkeypatch)
    transition = LifeTransition.from_dict(
        runner.run_episode(external_input=0.04)["life_transition"]
    )
    trace = {
        "backend_identities": {"N1": "reference"},
        "persistence_degraded": True,
        "organs": [
            {
                "organ": "N1",
                "candidate": {},
                "abstained": False,
                "latency": 0.1,
                "RAM": 0.1,
                "fallback_reason": None,
            }
        ],
        "consumer_receipts": [
            {"organ": "N1", "verdict_class": verdict, "persisted": True}
            for verdict in (
                "rejected",
                "abstained",
                "observed",
                "unavailable",
                "persistence_degraded",
            )
        ],
    }
    store = AdaptiveStateStore(
        organism_id="organism-longitudinal",
        lineage_id=runner.lineage.lineage_id,
    )
    state = store.update(transition, trace)[0]
    assert state.accepted_count == 0
    assert state.rejected_count == 1
    assert state.receipt_abstained_count == 1
    assert state.observed_count == 1
    assert state.unavailable_count == 1
    assert state.persistence_degraded_count == 1
    assert state.acceptance_denominator == 1
    assert state.consumer_acceptance_rate == 0.0
    storage.close()


def test_adaptive_state_and_regime_change_survive_checkpoint(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path)
    thermal = ScenarioEpisodeRunner(
        storage=storage, run_id="run-thermal", scenario="thermal_homeostasis"
    )
    thermal.set_organism_id("organism-regime")
    first = thermal.run_episode(external_input=0.04)
    checkpoint = thermal.export_neural_state()
    assert checkpoint["adaptive_state"]["states"]

    resource = ScenarioEpisodeRunner(
        storage=storage,
        run_id="run-resource",
        scenario="resource_management",
        organism_state=thermal.organism_state,
        lineage=thermal.lineage,
    )
    resource.set_organism_id("organism-regime")
    resource.restore_neural_state(checkpoint)
    second = resource.run_episode(external_input=0.04)
    assert second["life_transition"]["transition_index"] == 2
    assert (
        second["life_transition"]["previous_transition_hash"]
        == first["life_transition"]["transition_hash"]
    )
    regime = second["dynamic_state"]["regime"]
    assert regime["regime_id"] == "inventory_maximization"
    assert regime["regime_transition_type"] == "changed"
    assert regime["compatibility_with_previous_regime"] in {
        "compatible_regime", "transformable_regime", "non_transportable"
    }
    assert second["adaptation"]["states"]
    window = resource.build_dynamic_trajectory_window(size=8)
    assert {item.regime_after["regime_id"] for item in window.transitions} == {
        "inventory_maximization"
    }
    storage.close()


def test_fifty_episode_regime_checkpoint_pressure_replay_circuit(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path)
    thermal = ScenarioEpisodeRunner(
        storage=storage, run_id="run-50-thermal", scenario="thermal_homeostasis"
    )
    thermal.set_organism_id("organism-50")
    last = None
    for index in range(25):
        last = thermal.run_episode(external_input=0.04 + 0.002 * index)
    assert last is not None
    checkpoint = thermal.export_neural_state()
    assert checkpoint["dynamic_chain"]["transition_index"] == 25

    resource = ScenarioEpisodeRunner(
        storage=storage,
        run_id="run-50-resource",
        scenario="resource_management",
        organism_state=thermal.organism_state,
        lineage=thermal.lineage,
    )
    resource.set_organism_id("organism-50")
    resource.restore_neural_state(checkpoint)
    for index in range(25):
        if index == 10:
            resource.set_resource_signals(
                {
                    "cpu_pressure": 0.95,
                    "memory_pressure": 0.91,
                    "thermal_pressure": 0.90,
                    "msrc_budget_available": True,
                }
            )
        elif index == 11:
            resource.set_resource_signals({"msrc_budget_available": True})
        last = resource.run_episode(external_input=0.03 + 0.001 * index)

    assert last is not None
    assert last["life_transition"]["transition_index"] == 50
    assert last["neural_symbiosis_trace"]["trace_complete"] is True
    final_checkpoint = resource.export_neural_state()
    assert final_checkpoint["dynamic_chain"]["transition_index"] == 50
    assert final_checkpoint["adaptive_state"]["states"]
    replay = resource.replay_dynamic_trajectory(organ_id="N1", size=8)
    assert replay["writes_performed"] is False
    assert replay["original_chain_untouched"] is True
    assert resource.export_neural_state()["dynamic_chain"]["transition_index"] == 50
    assert all(
        priority["allowed_action"] in ALLOWED_ADAPTATION_ACTIONS
        for priority in last["adaptation"]["priorities"]
    )
    storage.close()
