from __future__ import annotations

from pathlib import Path

import pytest

from runtime.neural.integration import (
    SymbiosisIdentity,
    SymbiosisTrace,
    SymbioticNeuralCoordinator,
)
from runtime.storage import StorageConfig, StorageFactory
from runtime.world import ScenarioEpisodeRunner


def _storage(tmp_path: Path, name: str = "symbiosis"):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / f"{name}.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / f"{name}-artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _organ(trace: dict, name: str) -> dict:
    return next(item for item in trace["organs"] if item["organ"] == name)


def test_multiple_live_episodes_share_trace_and_close_all_consumption_loops(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    monkeypatch.setenv("RNFE_EXPERIENCE", "1")
    storage = _storage(tmp_path)
    runner = ScenarioEpisodeRunner(
        storage=storage,
        run_id="run-symbiotic-e2e",
        scenario="thermal_homeostasis",
        closure_profile="adaptive_min",
    )
    runner.set_organism_id("organism-e2e")
    runner.set_causal_context(
        {
            "organism_id": "organism-e2e",
            "lineage_id": runner.lineage.lineage_id,
            "run_id": "run-symbiotic-e2e",
            "trace_group_id": "trace-e2e-1",
            "decision_id": "decision-e2e-1",
        }
    )
    first = runner.run_episode(external_input=0.04)
    runner.set_causal_context(
        {
            "organism_id": "organism-e2e",
            "lineage_id": runner.lineage.lineage_id,
            "run_id": "run-symbiotic-e2e",
            "trace_group_id": "trace-e2e-2",
            "decision_id": "decision-e2e-2",
        }
    )
    second = runner.run_episode(external_input=0.14)

    first_trace = first["neural_symbiosis_trace"]
    second_trace = second["neural_symbiosis_trace"]
    assert first_trace["trace_complete"] is True
    assert second_trace["trace_complete"] is True
    assert first_trace["semantic_complete"] is True
    assert first_trace["durably_complete"] is True
    assert first_trace["persistence_degraded"] is False
    assert second_trace["schema_version"] == "neural-symbiosis-trace-v2"
    receipt_organs = {receipt["organ"] for receipt in second_trace["consumer_receipts"]}
    assert receipt_organs == {"N1", "N2", "N3", "N4", "N5", "N6"}
    candidate_hashes = {entry["organ"]: entry["candidate_hash"] for entry in second_trace["organs"]}
    assert all(
        receipt["candidate_hash"] == candidate_hashes[receipt["organ"]]
        for receipt in second_trace["consumer_receipts"]
    )
    first_transition = first["life_transition"]
    second_transition = second["life_transition"]
    assert first_transition["status"] == "committed"
    assert second_transition["transition_index"] == 2
    assert second_transition["previous_transition_hash"] == first_transition["transition_hash"]
    assert second_trace["life_transition_id"] == second_transition["transition_id"]
    assert second_trace["state_after_hash"] == second["dynamic_state"]["state_hash"]
    dropped = SymbiosisTrace.from_dict(second_trace)
    dropped.trace_health = {**dropped.trace_health, "dropped_events": 1}
    assert dropped.semantic_complete is True
    assert dropped.durably_complete is False
    assert dropped.persistence_degraded is True
    assert {entry["trace_group_id"] for entry in second_trace["organs"]} == {"trace-e2e-2"}
    assert {entry["organ"] for entry in second_trace["organs"]} == {
        "N1", "N2", "N3", "N4", "N5", "N6"
    }
    assert _organ(first_trace, "N3")["candidate"]["uncertainty"] == 0.5

    n5 = _organ(second_trace, "N5")
    assert n5["candidate"]["backend"] == "deterministic_chunker"
    assert n5["candidate"]["hnet_active"] is False
    assert n5["manifest_sha256"] is None
    assert n5["artifact_sha256"] is None
    assert n5["cost"]["reference_sha256"]
    assert second["episode"]["context"]["neural_ingestion"]["smg_sign_ids"]
    assert "SMG+MFM" in n5["consumer_verdict"]

    assert second["episode"]["context"]["retrieved_memory"]
    n1_comparison = second["episode"]["result"]["neural_comparisons"][
        "n1_scheduler_comparison"
    ]
    assert n1_comparison["scheduler_authority_preserved"] is True
    assert n1_comparison["scheduler_selected"] == second["reasoning"]["sequence"]

    n2 = _organ(second_trace, "N2")
    assert set(n2["candidate"]["verification"]) == {"DED", "LOT-F", "NESY"}
    assert n2["consumer"] == "DED+LOT-F+NESY"

    n3 = _organ(second_trace, "N3")["candidate"]
    assert n3["episode_count"] == 2
    assert n3["previous_state"]["episode_count"] == 1
    assert n3["state_key"] == [
        "organism-e2e",
        "thermal_homeostasis@1.0",
        runner.lineage.lineage_id,
    ]
    assert n3["mamba2_active"] is False

    n4 = _organ(second_trace, "N4")
    assert n4["effective_mode"] == "shadow"
    assert n4["candidate"]["authority"]["may_choose_intervention"] is False
    assert n4["candidate"]["canonical_comparison"]["decision_influence"] == "none"
    assert "certificate_metadata=consumed" in n4["consumer_verdict"]

    n6 = _organ(second_trace, "N6")
    assert n6["candidate"]["applied"] is False
    assert n6["candidate"]["sandbox"]["applied"] is False
    assert second["experience"]["neural_symbiosis"]["trace_group_id"] == "trace-e2e-2"

    certificate = storage.list_episode_certificates(run_id="run-symbiotic-e2e", limit=1)[0]
    neural_metadata = certificate.metadata["neural_symbiosis"]
    assert neural_metadata["verdict_influence"] == "none"
    assert neural_metadata["authority_effective"]["N4"] == "shadow"
    assert neural_metadata["runtime"]["loaded_artifacts"] == 0
    storage.close()


def test_off_ablation_preserves_world_but_removes_downstream_neural_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "off")
    off_storage = _storage(tmp_path, "off")
    off = ScenarioEpisodeRunner(
        storage=off_storage, run_id="run-off", scenario="thermal_homeostasis"
    ).run_episode(external_input=0.04)

    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    shadow_storage = _storage(tmp_path, "shadow")
    shadow = ScenarioEpisodeRunner(
        storage=shadow_storage, run_id="run-shadow", scenario="thermal_homeostasis"
    ).run_episode(external_input=0.04)

    assert off["episode"]["result"]["updated_world"] == shadow["episode"]["result"]["updated_world"]
    assert off["episode"]["context"]["intervention"] == shadow["episode"]["context"]["intervention"]
    assert all(entry["effective_mode"] == "off" for entry in off["neural_symbiosis_trace"]["organs"])
    assert not off["episode"]["context"]["neural_ingestion"]["smg_sign_ids"]
    assert _organ(shadow["neural_symbiosis_trace"], "N5")["candidate"]["chunks"]
    assert off_storage.list_episode_certificates(run_id="run-off", limit=1)[0].metadata[
        "neural_symbiosis"
    ]["runtime"]["loaded_artifacts"] == 0
    off_storage.close()
    shadow_storage.close()


def test_resource_pressure_degrades_optional_organs_but_keeps_ingestion_and_continuity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path, "pressure")
    runner = ScenarioEpisodeRunner(
        storage=storage, run_id="run-pressure", scenario="thermal_homeostasis"
    )
    runner.set_resource_signals(
        {"cpu_pressure": 0.95, "memory_pressure": 0.93, "thermal_pressure": 0.92}
    )
    result = runner.run_episode(external_input=0.14)
    trace = result["neural_symbiosis_trace"]

    for organ in ("N1", "N2", "N4", "N6"):
        assert _organ(trace, organ)["fallback_reason"] == "reference_degraded_by_resource_pressure"
    assert _organ(trace, "N5")["candidate"]["chunks"]
    assert _organ(trace, "N3")["candidate"]["episode_count"] == 1
    storage.close()


def test_missing_msrc_budget_prevents_all_neural_execution(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path, "no-msrc-budget")
    runner = ScenarioEpisodeRunner(
        storage=storage, run_id="run-no-budget", scenario="thermal_homeostasis"
    )
    runner.set_resource_signals(
        {"msrc_budget_available": False, "msrc_scale_id": "1x1"}
    )
    result = runner.run_episode(external_input=0.04)

    assert all(
        entry["fallback_reason"] == "msrc_budget_unavailable"
        for entry in result["neural_symbiosis_trace"]["organs"]
    )
    assert result["episode"]["context"]["neural_ingestion"]["smg_sign_ids"] == []
    storage.close()


@pytest.mark.parametrize("disabled", ["N1", "N2", "N3", "N4", "N5", "N6"])
def test_each_organ_ablation_changes_downstream_evidence(
    tmp_path: Path, monkeypatch, disabled: str
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    monkeypatch.setenv("RNFE_NEURAL_DISABLED_ORGANS", disabled)
    storage = _storage(tmp_path, f"ablation-{disabled.lower()}")
    result = ScenarioEpisodeRunner(
        storage=storage,
        run_id=f"run-ablation-{disabled.lower()}",
        scenario="thermal_homeostasis",
    ).run_episode(external_input=0.04)
    entry = _organ(result["neural_symbiosis_trace"], disabled)

    assert entry["effective_mode"] == "off"
    assert entry["candidate"] is None
    assert entry["fallback_reason"] == "organ_disabled_by_profile"
    assert entry["consumer_verdict"]
    if disabled == "N5":
        assert result["episode"]["context"]["neural_ingestion"]["smg_sign_ids"] == []
    elif disabled == "N4":
        comparison = result["episode"]["result"]["neural_comparisons"]["n4_comparison"]
        assert comparison["verdict"] == "disabled_or_no_candidate"
    elif disabled == "N2":
        verification = result["episode"]["result"]["neural_comparisons"]["n2_verification"]
        assert verification["status"] == "disabled"
    storage.close()


class _FailNeuralEvents:
    def __init__(self, storage):
        self._storage = storage

    def append_event(self, **kwargs):
        if str(kwargs.get("event_type", "")).startswith("neural."):
            raise OSError("simulated neural ledger outage")
        return self._storage.append_event(**kwargs)

    def __getattr__(self, name):
        return getattr(self._storage, name)


def test_neural_trace_storage_failure_is_visible_and_episode_still_finishes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    base = _storage(tmp_path, "degraded")
    runner = ScenarioEpisodeRunner(
        storage=_FailNeuralEvents(base),
        run_id="run-degraded",
        scenario="thermal_homeostasis",
    )
    result = runner.run_episode(external_input=0.04)

    assert result["certification"]["verdict"] in {"certified", "rejected"}
    trace = result["neural_symbiosis_trace"]
    assert trace["trace_persisted"] is False
    assert trace["semantic_complete"] is True
    assert trace["durably_complete"] is False
    assert trace["persistence_degraded"] is True
    assert trace["trace_health"]["degraded"] is True
    assert trace["trace_health"]["persistence_failures"] > 0
    assert trace["trace_health"]["pending_events"] > 0
    base.close()


def test_causal_conflict_is_consumed_as_disagreement_without_action_authority(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    storage = _storage(tmp_path, "conflict")
    coordinator = SymbioticNeuralCoordinator(storage=storage)
    identity = SymbiosisIdentity(
        trace_group_id="trace-conflict",
        organism_id="org-conflict",
        lineage_id="lin-conflict",
        run_id="run-conflict",
        episode_id="episode-conflict",
        scenario_id="scenario@1",
        decision_id="decision-conflict",
    )
    coordinator.begin_episode(
        identity=identity,
        observation={"temperature": 0.9, "alarm": True},
        formula="temperature > alarm_threshold",
        proposition="temperature alarm",
        memory_hits=[],
        scenario_metadata={"main_variable": "temperature"},
            causal_attestation={
                "main_variable": "temperature",
                "optimization_direction": "minimize",
                "factual_delta": -0.1,
            "counterfactual_delta": 0.1,
            "supports_choice": True,
        },
        resources={},
    )
    comparison = coordinator.consume_reasoning(
        episode_id="episode-conflict",
        reasoning={
            "sequence": ["CAU", "CTF", "DED"],
            "state": {
                "cau_link": {"helps_goal": False},
                "ctf_checked": {"supports_choice": False},
                "ded_validated": True,
                "ded_conclusion": "safe",
            },
        },
        lotf_valid=True,
    )["n4_comparison"]
    assert comparison["verdict"] == "disagreement"
    assert comparison["decision_influence"] == "none"
    storage.close()
