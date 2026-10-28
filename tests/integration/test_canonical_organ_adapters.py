from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from runtime.neural.contracts import InferenceScope, NeuralInferenceRequest, ResourceSnapshot
from runtime.neural.integration.adapters import N3Adapter, N4Adapter
from runtime.neural.integration import (
    SymbiosisIdentity,
    SymbioticNeuralCoordinator,
    canonical_adapter_registry,
)
from runtime.neural.organs.n4_causal import (
    CausalMessagePassingBackend,
    CausalPredictionAdmission,
)
from runtime.storage import StorageConfig, StorageFactory


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "canonical-adapters.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def test_registry_has_one_canonical_adapter_per_organ_and_no_inline_producers() -> None:
    registry = canonical_adapter_registry()
    assert set(registry) == {"N1", "N2", "N3", "N4", "N5", "N6"}
    assert {adapter.organ for adapter in registry.values()} == set(registry)
    source = inspect.getsource(SymbioticNeuralCoordinator)
    for organ in range(1, 7):
        assert f"def _n{organ}" not in source


def test_live_n4_path_calls_canonical_typed_backend(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    calls: list[str] = []
    original = CausalMessagePassingBackend.infer

    def observed(self, request):
        calls.append(str(request.payload["graph"]["schema_version"]))
        return original(self, request)

    monkeypatch.setattr(CausalMessagePassingBackend, "infer", observed)
    storage = _storage(tmp_path)
    coordinator = SymbioticNeuralCoordinator(storage=storage)
    coordinator.begin_episode(
        identity=SymbiosisIdentity(
            trace_group_id="trace-adapter",
            organism_id="organism-adapter",
            lineage_id="lineage-adapter",
            run_id="run-adapter",
            episode_id="episode-adapter",
            scenario_id="scenario@1",
            decision_id="decision-adapter",
        ),
        observation={"temperature": 0.8},
        formula="temperature > 0.5",
        proposition="temperature high",
        memory_hits=[],
        scenario_metadata={"main_variable": "temperature"},
        causal_attestation={
            "main_variable": "temperature",
            "optimization_direction": "minimize",
            "factual_delta": -0.2,
            "counterfactual_delta": 0.1,
            "supports_choice": True,
        },
        resources={},
    )
    assert calls == ["n4-causal-graph-v1"]
    storage.close()


def _identity(episode: str = "episode-evidence") -> SymbiosisIdentity:
    return SymbiosisIdentity(
        trace_group_id=f"trace-{episode}",
        organism_id="organism-evidence",
        lineage_id="lineage-evidence",
        run_id="run-evidence",
        episode_id=episode,
        scenario_id="scenario@1",
        decision_id="decision-evidence",
    )


def _request(identity: SymbiosisIdentity, organ: str, capability: str) -> NeuralInferenceRequest:
    return NeuralInferenceRequest(
        inference_id=f"inference-{organ.lower()}",
        run_id=identity.run_id,
        organ=organ,
        capability=capability,
        payload={},
        scope=InferenceScope.LIVE,
        resources=ResourceSnapshot(),
    )


def test_n4_live_path_executes_canonical_admission_and_preserves_rejected_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    admission_calls: list[str] = []
    original = CausalPredictionAdmission.__call__

    def observed(self, candidate, request):
        admission_calls.append(request.organ)
        return original(self, candidate, request)

    monkeypatch.setattr(CausalPredictionAdmission, "__call__", observed)
    storage = _storage(tmp_path)
    coordinator = SymbioticNeuralCoordinator(storage=storage)
    identity = _identity("zero-effect")
    coordinator.begin_episode(
        identity=identity,
        observation={"temperature": 0.8},
        formula="temperature > 0.5",
        proposition="temperature high",
        memory_hits=[],
        scenario_metadata={"main_variable": "temperature"},
        causal_attestation={
            "main_variable": "temperature",
            "optimization_direction": "minimize",
            "factual_delta": 0.1,
            "counterfactual_delta": 0.1,
            "supports_choice": True,
        },
        resources={},
    )
    n4 = coordinator._session(identity.episode_id).entries["N4"]
    assert admission_calls == ["N4"]
    assert n4.candidate["causal_effect"]["signed_effect"] == 0.0
    assert n4.candidate["causal_effect"]["episodic_edge_id"] is None
    assert n4.candidate["relations"] == []
    assert n4.fallback_reason == "n4_insufficient_evidence_fallback"
    assert n4.effective_mode == "shadow"
    assert coordinator._session(identity.episode_id).trace.measurement_status[
        "cpu_pressure"
    ] == "defaulted"
    storage.close()


def test_n4_causal_sign_is_independent_of_supports_choice_and_canon_is_separate() -> None:
    identity = _identity()
    metadata = {
        "main_variable": "temperature",
        "causal_signature": {
            "scenario_name": "thermal",
            "scenario_version": "1",
            "intervention_effects": [
                {
                    "intervention_name": "cool",
                    "target_variable": "temperature",
                    "expected_direction": "-",
                    "expected_magnitude": 0.4,
                }
            ],
        },
    }
    base = {
        "observation": {"temperature": 0.9},
        "scenario_metadata": metadata,
        "causal_attestation": {
            "main_variable": "temperature",
            "intervention": "cool",
            "optimization_direction": "minimize",
            "factual_delta": -0.2,
            "counterfactual_delta": 0.1,
        },
    }
    graph_true, evidence_true = N4Adapter._graph(
        identity,
        {**base, "causal_attestation": {**base["causal_attestation"], "supports_choice": True}},
    )
    graph_false, evidence_false = N4Adapter._graph(
        identity,
        {**base, "causal_attestation": {**base["causal_attestation"], "supports_choice": False}},
    )
    assert evidence_true["causal_effect"]["signed_effect"] == pytest.approx(-0.3)
    assert evidence_false["causal_effect"]["signed_effect"] == pytest.approx(-0.3)
    assert graph_true == graph_false
    episodic, canonical = graph_true["edges"]
    assert episodic["canonical"] is False
    assert canonical["canonical"] is True
    assert episodic["id"] != canonical["id"]
    assert canonical["provenance"].startswith("scenario.causal_signature:")
    assert evidence_true["goal_alignment"]["status"] == "helps_goal"


def test_n4_missing_variable_and_deltas_remain_insufficient_not_zero() -> None:
    graph, evidence = N4Adapter._graph(
        _identity(),
        {
            "observation": {},
            "scenario_metadata": {},
            "causal_attestation": {"supports_choice": True},
        },
    )
    assert graph["edges"] == []
    assert graph["nodes"][0]["node_type"] == "evidence"
    assert evidence["causal_effect"]["signed_effect"] is None
    assert evidence["causal_effect"]["measurement_status"] == "unmeasured"
    assert evidence["evidence_status"] == "insufficient_evidence"


def test_n3_absence_does_not_become_zero_or_increment_measurements() -> None:
    adapter = N3Adapter()
    identity = _identity("n3-measured")
    request = _request(identity, "N3", adapter.capability)
    measured = adapter.infer(
        request,
        {
            "identity": identity,
            "inputs": {
                "observation": {"temperature": 0.0},
                "scenario_metadata": {"main_variable": "temperature"},
            },
        },
    ).candidate_output
    assert measured["value"] == 0.0
    assert measured["measurement_status"] == "measured"
    assert measured["measurement_count"] == 1

    absent_identity = _identity("n3-absent")
    absent = adapter.infer(
        _request(absent_identity, "N3", adapter.capability),
        {
            "identity": absent_identity,
            "inputs": {
                "observation": {},
                "scenario_metadata": {"main_variable": "temperature"},
            },
        },
    ).candidate_output
    assert absent["value"] is None
    assert absent["trend"] is None
    assert absent["measurement_status"] == "unmeasured"
    assert absent["measurement_count"] == 1
