from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from runtime.neural import (
    CausalContextView,
    DecisionInfluence,
    DevicePreference,
    InferenceScope,
    LazyBackendRegistry,
    NeuralInferenceRequest,
    NeuralMode,
    NeuralModelManifest,
    NeuralRuntime,
    NeuralRuntimeConfig,
    ResourceSnapshot,
)
from runtime.neural.organs.n4_causal import (
    ARTIFACT_SCHEMA_VERSION,
    GRAPH_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    CausalMessagePassingBackend,
    CausalPredictionAdmission,
    DisagreementStatus,
)
from runtime.neural.lab.n4_benchmark import run_n4_synthetic_benchmark


def _artifact_payload(*, supported_node_types: list[str] | None = None) -> dict:
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_kind": "reference",
        "trained": False,
        "frozen": True,
        "experimental": True,
        "input_size": 2,
        "hidden_size": 2,
        "message_passing_steps": 2,
        "max_nodes": 32,
        "max_edges": 64,
        "input_weight": [[1.0, 0.0], [0.0, 1.0]],
        "message_weight": [[0.5, 0.0], [0.0, 0.5]],
        "update_weight": [[0.8, 0.0], [0.0, 0.8]],
        "output_weight": [
            [0.2, 0.1],
            [0.1, 0.1],
            [0.0, 0.0],
            [0.0, 0.0],
        ],
        "supported_node_types": supported_node_types
        or [
            "world_variable",
            "observation",
            "intervention",
            "sign",
            "evidence",
            "memory",
            "goal",
            "constraint",
        ],
        "supported_edge_types": [
            "causal_positive",
            "causal_negative",
            "temporal",
            "support",
            "contradiction",
            "counterfactual",
            "semantic",
            "morphism",
        ],
    }


def _manifest(root: Path, payload: dict | None = None, *, devices: tuple[str, ...] = ("cpu",)):
    payload = payload or _artifact_payload()
    target = root / "n4" / "reference.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return NeuralModelManifest(
        organ="N4",
        capability="causal_prediction",
        model_id="n4-reference-contract",
        version="1.0.0",
        backend="n4-reference",
        artifact_path="n4/reference.json",
        artifact_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        input_schema_version=GRAPH_SCHEMA_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        supported_devices=devices,
        parameter_count=32,
        peak_vram_gb=0.0,
        license_id="Unlicense",
        upstream_url="repo://rnfe/runtime/neural/organs/n4_causal.py",
        upstream_commit="reference-contract-v1",
        training_provenance={"classification": "reference", "trained": False},
    )


def _node(
    node_id: str,
    node_type: str,
    features: tuple[float, float],
    *,
    scenario_id: str = "scenario-a",
    provenance: str = "fixture:node",
) -> dict:
    return {
        "id": node_id,
        "node_type": node_type,
        "feature_vector": list(features),
        "provenance": provenance,
        "scenario_id": scenario_id,
        "timestamp": "2026-07-11T00:00:00Z",
        "schema_version": GRAPH_SCHEMA_VERSION,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str,
    strength: float,
    *,
    confidence: float = 0.9,
    canonical: bool = False,
    provenance: str = "fixture:edge",
) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "edge_type": edge_type,
        "signed_strength": strength,
        "confidence": confidence,
        "provenance": provenance,
        "canonical": canonical,
        "schema_version": GRAPH_SCHEMA_VERSION,
    }


def _graph(*, nodes: list[dict] | None = None, edges: list[dict] | None = None) -> dict:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "scenario_id": "scenario-a",
        "nodes": nodes
        or [
            _node("do-x", "intervention", (1.0, 0.0)),
            _node("x", "world_variable", (0.0, 1.0)),
            _node("y", "observation", (0.5, 0.5)),
        ],
        "edges": edges
        or [
            _edge("canonical-positive", "do-x", "x", "causal_positive", 0.8, canonical=True),
            _edge("negative", "x", "y", "causal_negative", -0.7, canonical=True),
        ],
    }


def _request(
    graph: dict,
    *,
    scope: InferenceScope = InferenceScope.LAB,
    linked: bool = False,
) -> NeuralInferenceRequest:
    return NeuralInferenceRequest(
        inference_id="n4-inference",
        run_id="n4-run",
        organ="N4",
        capability="causal_prediction",
        payload={"graph": graph},
        seed=17,
        scope=scope,
        resources=ResourceSnapshot(),
        causal_context=(
            CausalContextView(organism_id="organism-n4", decision_id="decision-n4")
            if linked
            else None
        ),
    )


def _loaded_backend(tmp_path: Path, payload: dict | None = None):
    root = tmp_path / "artifacts" / "neural"
    manifest = _manifest(root, payload)
    backend = CausalMessagePassingBackend()
    backend.load(manifest, str(root / manifest.artifact_path), "cpu")
    return backend, manifest


def test_typed_signed_predictions_are_deterministic_and_do_not_mutate_graph(tmp_path: Path) -> None:
    backend, manifest = _loaded_backend(tmp_path)
    graph = _graph()
    original = deepcopy(graph)
    first = backend.infer(_request(graph))
    second = backend.infer(_request(graph))

    assert graph == original
    assert first == second
    candidate = first.candidate_output
    assert candidate["schema_version"] == OUTPUT_SCHEMA_VERSION
    assert candidate["graph_schema_version"] == GRAPH_SCHEMA_VERSION
    assert "graph_mutations" not in candidate
    assert "action" not in candidate
    assert candidate["authority"] == {
        "proposal_only": True,
        "may_mutate_graph": False,
        "may_choose_intervention": False,
        "may_authorize_action": False,
        "authoritative_systems": ["CAU", "CTF", "C-GWM", "LOTF", "DED"],
    }
    positive, negative = candidate["relations"]
    assert positive["signed_expected_effect"] > 0.0
    assert negative["signed_expected_effect"] < 0.0
    assert positive["magnitude"] == abs(positive["signed_expected_effect"])
    assert negative["magnitude"] == abs(negative["signed_expected_effect"])
    assert positive["uncertainty"] != positive["magnitude"]
    assert positive["model_identity"]["model_hash"] == manifest.artifact_sha256
    assert positive["model_identity"]["classification"] == "reference"
    assert positive["model_identity"]["trained"] is False
    assert positive["model_identity"]["frozen"] is True
    assert positive["model_identity"]["experimental"] is True
    assert set(positive["next_state_bounded_estimate"]) == {"lower", "mean", "upper"}
    admission = CausalPredictionAdmission()(candidate, _request(graph))
    assert admission.accepted is True
    assert admission.effective_mode_ceiling is NeuralMode.SHADOW


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda graph: graph["nodes"][0].update(node_type="unknown"), "unknown_node_type"),
        (lambda graph: graph["edges"][0].update(edge_type="unknown"), "unknown_edge_type"),
        (lambda graph: graph["nodes"].append(deepcopy(graph["nodes"][0])), "duplicate_node_id"),
        (lambda graph: graph["edges"].append(deepcopy(graph["edges"][0])), "duplicate_edge_id"),
        (lambda graph: graph["edges"][0].update(target="missing"), "dangling_edge"),
        (lambda graph: graph["nodes"][0]["feature_vector"].__setitem__(0, math.nan), "must_be_finite"),
        (lambda graph: graph["nodes"][0]["feature_vector"].__setitem__(0, math.inf), "must_be_finite"),
        (lambda graph: graph["edges"][0].update(confidence=1.5), "confidence_out_of_range"),
        (lambda graph: graph["edges"][0].update(signed_strength=-0.2), "unsigned_causal_edge"),
        (lambda graph: graph["nodes"][0].update(provenance=""), "node_provenance_required"),
        (lambda graph: graph["edges"][0].update(provenance=""), "edge_provenance_required"),
        (lambda graph: graph.update(schema_version="n4-causal-graph-v999"), "graph_schema_mismatch"),
        (
            lambda graph: graph["nodes"][1].update(scenario_id="scenario-b"),
            "inconsistent_scenario_identity",
        ),
    ],
)
def test_malformed_typed_graphs_fail_closed(tmp_path: Path, mutator, reason: str) -> None:
    backend, _ = _loaded_backend(tmp_path)
    graph = _graph()
    mutator(graph)
    with pytest.raises(ValueError, match=reason):
        backend.infer(_request(graph))


def test_direction_conflict_missing_canonical_and_contradiction_are_explicit(tmp_path: Path) -> None:
    backend, _ = _loaded_backend(tmp_path)
    graph = _graph(
        edges=[
            _edge("canon", "do-x", "x", "causal_positive", 0.8, canonical=True),
            _edge("counter", "do-x", "x", "counterfactual", -0.8),
            _edge("missing", "x", "y", "causal_positive", 0.6),
            _edge("contradiction", "do-x", "x", "contradiction", -0.9),
        ]
    )
    output = backend.infer(_request(graph)).candidate_output
    statuses = {
        item["relation_edge_id"]: item["canonical_disagreement"]["status"]
        for item in output["relations"]
    }
    assert statuses["canon"] == DisagreementStatus.WEAK_DISAGREEMENT.value
    assert statuses["counter"] == DisagreementStatus.DIRECTION_CONFLICT.value
    assert statuses["missing"] == DisagreementStatus.MISSING_CANONICAL_EDGE.value
    admission = CausalPredictionAdmission()(output, _request(graph))
    assert admission.accepted is True
    assert admission.output["direction_conflicts"] == ["n4:counter"]
    assert admission.output["confidence_after_disagreement_gate"] <= 0.25
    assert admission.output["admission_scope"] == "shadow_logging_only"


def test_ood_and_cross_scenario_morphism_report_insufficient_evidence(tmp_path: Path) -> None:
    supported = [
        "world_variable",
        "observation",
        "intervention",
        "sign",
        "evidence",
        "goal",
        "constraint",
    ]
    backend, _ = _loaded_backend(tmp_path, _artifact_payload(supported_node_types=supported))
    graph = _graph(
        nodes=[
            _node("memory", "memory", (1.0, 0.0)),
            _node("other", "world_variable", (0.0, 1.0), scenario_id="scenario-b"),
        ],
        edges=[_edge("morphism", "memory", "other", "morphism", 0.5)],
    )
    relation = backend.infer(_request(graph)).candidate_output["relations"][0]
    assert relation["ood"] is True
    assert set(relation["ood_reasons"]) == {"source_node_pattern", "cross_scenario_pattern"}
    assert relation["uncertainty"] >= 0.85
    assert relation["confidence"] <= 0.15
    assert relation["insufficient_evidence"] is True
    assert (
        relation["canonical_disagreement"]["status"]
        == DisagreementStatus.INSUFFICIENT_EVIDENCE.value
    )


def test_no_relation_requires_deterministic_authority_fallback(tmp_path: Path) -> None:
    backend, _ = _loaded_backend(tmp_path)
    graph = _graph(edges=[_edge("support", "do-x", "x", "support", 0.5)])
    candidate = backend.infer(_request(graph)).candidate_output
    assert candidate["relations"] == []
    assert candidate["fallback"] == {
        "required": True,
        "route": "deterministic_causal_authorities",
        "reason": "insufficient_evidence",
    }
    admission = CausalPredictionAdmission()(candidate, _request(graph))
    assert admission.accepted is False
    assert admission.reason == "n4_insufficient_evidence_fallback"


def test_reference_artifact_labels_and_graph_resource_budget_fail_closed(tmp_path: Path) -> None:
    bad_reference = _artifact_payload()
    bad_reference["trained"] = True
    root = tmp_path / "bad-reference"
    manifest = _manifest(root, bad_reference)
    with pytest.raises(ValueError, match="reference_model_cannot_claim_trained"):
        CausalMessagePassingBackend().load(
            manifest, str(root / manifest.artifact_path), "cpu"
        )

    missing_evidence = _artifact_payload()
    missing_evidence.update(model_kind="trained", trained=True)
    root = tmp_path / "missing-evidence"
    manifest = _manifest(root, missing_evidence)
    with pytest.raises(ValueError, match="trained_model_requires_training_evidence"):
        CausalMessagePassingBackend().load(
            manifest, str(root / manifest.artifact_path), "cpu"
        )

    missing_uncertainty = _artifact_payload()
    missing_uncertainty["output_weight"] = missing_uncertainty["output_weight"][:3]
    root = tmp_path / "missing-uncertainty"
    manifest = _manifest(root, missing_uncertainty)
    with pytest.raises(ValueError, match="separate_uncertainty_head_required"):
        CausalMessagePassingBackend().load(
            manifest, str(root / manifest.artifact_path), "cpu"
        )

    backend, _ = _loaded_backend(tmp_path / "budget")
    graph = _graph()
    graph["nodes"] = [
        _node(f"node-{index}", "world_variable", (0.0, 0.0)) for index in range(33)
    ]
    graph["edges"] = []
    with pytest.raises(ValueError, match="node_budget_exceeded"):
        backend.infer(_request(graph))


class _FlakyStorage:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def append_event(self, **kwargs):
        raise OSError("n4-trace-store-unavailable")


def _runtime(
    tmp_path: Path,
    mode: NeuralMode,
    *,
    storage=None,
    manifest_devices: tuple[str, ...] = ("cpu",),
    digest_override: str | None = None,
):
    root = tmp_path / "runtime-artifacts" / "neural"
    manifest = _manifest(root, devices=manifest_devices)
    if digest_override is not None:
        manifest = NeuralModelManifest.from_dict(
            {**manifest.to_dict(), "artifact_sha256": digest_override}
        )
    registry = LazyBackendRegistry(artifact_root=root)
    registry.register("n4-reference", CausalMessagePassingBackend)
    runtime = NeuralRuntime(
        config=NeuralRuntimeConfig(mode=mode, device_preference=DevicePreference.AUTO),
        registry=registry,
        storage=storage,
    )
    return runtime, registry, manifest


def test_modes_hash_resources_and_trace_failure_preserve_authority(tmp_path: Path) -> None:
    graph = _graph()
    request = _request(graph, scope=InferenceScope.LIVE)
    linked_request = _request(graph, scope=InferenceScope.LIVE, linked=True)

    off_runtime, off_registry, manifest = _runtime(tmp_path / "off", NeuralMode.OFF)
    off = off_runtime.infer(request=request, manifest=manifest, fallback_output={"authority": "CAU"})
    assert off.candidate_output is None
    assert off.effective_output == {"authority": "CAU"}
    assert off_registry.loaded_count == 0

    shadow_runtime, _, manifest = _runtime(tmp_path / "shadow", NeuralMode.SHADOW)
    shadow = shadow_runtime.infer(
        request=request,
        manifest=manifest,
        fallback_output={"authority": "CAU"},
        admission_gate=CausalPredictionAdmission(),
    )
    assert shadow.candidate_output["relations"]
    assert shadow.effective_output == {"authority": "CAU"}
    assert shadow.decision_influence.value == "none"

    provisional_runtime, _, manifest = _runtime(
        tmp_path / "provisional", NeuralMode.PROVISIONAL
    )
    provisional = provisional_runtime.infer(
        request=linked_request,
        manifest=manifest,
        fallback_output={"authority": "CAU"},
        admission_gate=CausalPredictionAdmission(),
    )
    assert provisional.effective_mode is NeuralMode.SHADOW
    assert provisional.effective_output == {"authority": "CAU"}
    assert provisional.candidate_output["relations"]
    assert provisional.decision_influence is DecisionInfluence.NONE
    assert provisional.fallback_used is True
    assert provisional.fallback_reason == "admission_authority_ceiling:shadow"

    bad_hash_runtime, _, bad_manifest = _runtime(
        tmp_path / "bad-hash", NeuralMode.SHADOW, digest_override="0" * 64
    )
    bad_hash = bad_hash_runtime.infer(
        request=request, manifest=bad_manifest, fallback_output={"authority": "CAU"}
    )
    assert "artifact_sha256_mismatch" in (bad_hash.fallback_reason or "")

    rejected_runtime, rejected_registry, cuda_manifest = _runtime(
        tmp_path / "resource", NeuralMode.SHADOW, manifest_devices=("cuda",)
    )
    rejected = rejected_runtime.infer(
        request=request,
        manifest=cuda_manifest,
        fallback_output={"authority": "CAU"},
    )
    assert rejected.fallback_reason == "no_supported_device_available"
    assert rejected_registry.loaded_count == 0

    flaky = _FlakyStorage()
    traced_runtime, _, manifest = _runtime(
        tmp_path / "trace", NeuralMode.PROVISIONAL, storage=flaky
    )
    traced = traced_runtime.infer(
        request=linked_request,
        manifest=manifest,
        fallback_output={"authority": "CAU"},
        admission_gate=CausalPredictionAdmission(),
    )
    assert traced.effective_output == {"authority": "CAU"}
    assert traced.effective_mode is NeuralMode.SHADOW
    assert traced.decision_influence is DecisionInfluence.NONE
    assert traced.fallback_reason == "admission_authority_ceiling:shadow"
    assert traced_runtime.trace_health.degraded is True
    assert traced_runtime.trace_health.persistence_failures == 4
    assert traced_runtime.trace_health.pending_events == 4


def test_admission_rejects_any_attempt_to_emit_mutation_or_action(tmp_path: Path) -> None:
    backend, _ = _loaded_backend(tmp_path)
    graph = _graph()
    candidate = backend.infer(_request(graph)).candidate_output
    forbidden_outputs = {
        "action",
        "authorization",
        "certificate",
        "closure_decision",
        "effective_output",
        "graph_mutations",
        "selected_intervention",
    }
    assert forbidden_outputs.isdisjoint(candidate)
    for forbidden in forbidden_outputs:
        malformed = {**candidate, forbidden: [] if forbidden == "graph_mutations" else "x"}
        decision = CausalPredictionAdmission()(malformed, _request(graph))
        assert decision.accepted is False
        assert decision.reason == "n4_forbidden_authority_output"
    missing_hash = dict(candidate)
    missing_hash.pop("input_graph_hash")
    decision = CausalPredictionAdmission()(missing_hash, _request(graph))
    assert decision.accepted is False
    assert "input_graph_hash_required" in decision.reason


def test_synthetic_benchmark_covers_topologies_metrics_resources_and_a_m0(tmp_path: Path) -> None:
    backend, _ = _loaded_backend(tmp_path)
    report = run_n4_synthetic_benchmark(backend, repeat_ids=(11, 23, 47))
    assert report["schema_version"] == "n4-contract-benchmark-v2"
    assert report["experiment_design"] == {
        "case_count": 10,
        "repetitions": 3,
        "repeat_identifiers": [11, 23, 47],
        "repetition_semantics": "deterministic_repeated_run_reproducibility",
        "independent_trained_models": 0,
    }
    assert report["samples"] == 30
    assert report["case_ids"] == [
        "positive_causal_effect",
        "negative_causal_effect",
        "causal_chain",
        "collider",
        "confounder_like_ambiguous",
        "contradiction_edge",
        "missing_canonical_edge",
        "cross_scenario_morphism",
        "factual_counterfactual_disagreement",
        "out_of_distribution_pattern",
    ]
    assert len(report["artifact_identity"]) == 1
    assert report["artifact_identity"][0]["classification"] == "reference"
    assert report["artifact_identity"][0]["trained"] is False
    contract = report["contract_metrics"]
    assert contract["signed_effect_contract_consistency"] == 1.0
    assert contract["canonical_disagreement_rule_precision"] == 1.0
    assert contract["canonical_disagreement_rule_recall"] == 1.0
    assert contract["malformed_graph_rejection_rate"] == 1.0
    assert contract["authority_invariant_pass_rate"] == 1.0
    assert contract["deterministic_repeatability"] == 1.0
    assert 0.0 < contract["fallback_rate"] < 1.0
    assert contract["schema_trace_completeness"] == 1.0
    predictive = report["predictive_metrics"]
    assert predictive == {
        "status": "not_evaluated_as_trained_model",
        "causal_generalization": "not_evaluated",
        "held_out_prediction": "not_evaluated",
        "intervention_effect_learning": "not_evaluated",
        "external_multiseed_generalization": "not_evaluated",
        "calibration_ece": predictive["calibration_ece"],
        "promotion_eligible": False,
    }
    assert 0.0 < predictive["calibration_ece"] <= 1.0
    assert "metrics" not in report
    assert "seeds" not in report
    assert report["resources"]["latency_mean_ms"] >= 0.0
    assert report["resources"]["latency_p95_ms"] >= 0.0
    assert report["resources"]["peak_python_allocation_bytes"] > 0
    assert report["resources"]["estimated_ram_bytes"] > 0
    assert report["resources"]["estimated_vram_bytes"] == 0
    assert report["resources"]["bounded_reference_profile"] is True
    assert all(report["a_m0"].values())
    assert report["operational_influence"] == "none"
    assert report["evidence_scope"] == "contract_conformance_only"
