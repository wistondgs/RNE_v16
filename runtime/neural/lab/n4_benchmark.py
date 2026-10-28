"""Benchmark sintetico reproducible para el contrato N4 tipado.

No entrena, promueve ni conecta N4 con autoridades vivas. El caller entrega un
backend ya cargado y recibe evidencia JSON-safe de contrato, recursos y A-M0.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
import statistics
import time
import tracemalloc
from typing import Any, Mapping, Sequence

from ..contracts import InferenceScope, NeuralInferenceRequest, ResourceSnapshot
from ..organs.n4_causal import (
    GRAPH_SCHEMA_VERSION,
    CausalMessagePassingBackend,
    DisagreementStatus,
)


BENCHMARK_SCHEMA_VERSION = "n4-contract-benchmark-v2"


def run_n4_synthetic_benchmark(
    backend: CausalMessagePassingBackend,
    *,
    repeat_ids: Sequence[int] = (11, 23, 47),
) -> dict[str, Any]:
    """Repite diez topologias para validar contrato, no aprendizaje causal."""

    unique_repeat_ids = tuple(dict.fromkeys(int(item) for item in repeat_ids))
    if len(unique_repeat_ids) < 3:
        raise ValueError("n4_benchmark_requires_three_repeated_runs")
    cases = _synthetic_cases()
    sign_hits: list[float] = []
    conflict_truth: list[bool] = []
    conflict_predicted: list[bool] = []
    calibration_rows: list[tuple[float, float]] = []
    latencies_ms: list[float] = []
    authority_checks: list[float] = []
    schema_trace_checks: list[float] = []
    case_fingerprints: dict[str, list[str]] = {case["case_id"]: [] for case in cases}
    model_identities: dict[str, Mapping[str, Any]] = {}
    fallback_count = 0
    relation_count = 0
    peak_ram_bytes = 0
    estimated_ram_bytes = 0
    estimated_vram_bytes = 0
    contract_trace_complete = True
    no_state_mutation = True
    no_graph_mutation = True
    no_action_authorization = True
    no_closure_influence = True
    no_certification_influence = True
    case_evidence: list[dict[str, Any]] = []

    for repeat_id in unique_repeat_ids:
        for case in cases:
            graph = deepcopy(case["graph"])
            before = deepcopy(graph)
            request = _request(graph, repeat_id=repeat_id, case_id=case["case_id"])
            tracemalloc.start()
            started = time.perf_counter()
            output = backend.infer(request)
            latency_ms = (time.perf_counter() - started) * 1_000.0
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            latencies_ms.append(latency_ms)
            peak_ram_bytes = max(peak_ram_bytes, peak)
            estimated_ram_bytes = max(
                estimated_ram_bytes, int(output.cost.get("estimated_ram_bytes", 0))
            )
            estimated_vram_bytes = max(
                estimated_vram_bytes, int(output.cost.get("estimated_vram_bytes", 0))
            )
            candidate = output.candidate_output
            relations = candidate["relations"]
            model = candidate["model"]
            model_identities[str(model["model_hash"])] = model
            case_fingerprints[case["case_id"]].append(
                json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            )
            fallback_count += int(bool(candidate["fallback"]["required"]))
            relation_count += len(relations)
            no_state_mutation = no_state_mutation and graph == before
            no_graph_mutation = no_graph_mutation and "graph_mutations" not in candidate
            sample_no_action_authorization = not any(
                key in candidate for key in ("action", "selected_intervention", "authorization")
            )
            sample_no_closure_influence = not any(
                key in candidate for key in ("closure", "closure_decision", "effective_output")
            )
            sample_no_certification_influence = not any(
                key in candidate for key in ("certificate", "certification", "certified")
            )
            no_action_authorization = (
                no_action_authorization and sample_no_action_authorization
            )
            no_closure_influence = no_closure_influence and sample_no_closure_influence
            no_certification_influence = (
                no_certification_influence and sample_no_certification_influence
            )
            authority = candidate.get("authority", {})
            authority_ok = bool(
                graph == before
                and "graph_mutations" not in candidate
                and sample_no_action_authorization
                and sample_no_closure_influence
                and sample_no_certification_influence
                and authority.get("proposal_only") is True
                and authority.get("may_mutate_graph") is False
                and authority.get("may_choose_intervention") is False
                and authority.get("may_authorize_action") is False
            )
            authority_checks.append(float(authority_ok))
            sample_trace_complete = len(output.trace) == len(relations)
            relation_statuses = {}
            for relation in relations:
                edge_id = relation["relation_edge_id"]
                relation_statuses[edge_id] = relation["canonical_disagreement"]["status"]
                expected_sign = case["expected_signs"].get(edge_id)
                if expected_sign is not None:
                    predicted_sign = -1 if relation["signed_expected_effect"] < 0.0 else 1
                    correct = float(predicted_sign == expected_sign)
                    sign_hits.append(correct)
                    calibration_rows.append((float(relation["confidence"]), correct))
                expected_conflict = edge_id in case["expected_direction_conflicts"]
                predicted_conflict = (
                    relation["canonical_disagreement"]["status"]
                    == DisagreementStatus.DIRECTION_CONFLICT.value
                )
                conflict_truth.append(expected_conflict)
                conflict_predicted.append(predicted_conflict)
                sample_trace_complete = sample_trace_complete and bool(
                    relation["supporting_node_ids"]
                    and relation["supporting_edge_ids"]
                    and relation["model_identity"]["model_hash"]
                    and relation["graph_schema_version"] == GRAPH_SCHEMA_VERSION
                )
            contract_trace_complete = contract_trace_complete and sample_trace_complete
            schema_trace_checks.append(float(sample_trace_complete))
            case_evidence.append(
                {
                    "case_id": case["case_id"],
                    "repeat_id": repeat_id,
                    "relations": len(relations),
                    "fallback_required": candidate["fallback"]["required"],
                    "statuses": relation_statuses,
                    "latency_ms": latency_ms,
                }
            )

    malformed_rejections = _measure_malformed_rejection(backend)
    precision, recall = _binary_precision_recall(conflict_truth, conflict_predicted)
    p95_index = max(0, math.ceil(0.95 * len(latencies_ms)) - 1)
    sorted_latencies = sorted(latencies_ms)
    deterministic_repeatability = statistics.fmean(
        float(len(set(fingerprints)) == 1) for fingerprints in case_fingerprints.values()
    )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "experiment_design": {
            "case_count": len(cases),
            "repetitions": len(unique_repeat_ids),
            "repeat_identifiers": list(unique_repeat_ids),
            "repetition_semantics": "deterministic_repeated_run_reproducibility",
            "independent_trained_models": 0,
        },
        "case_ids": [case["case_id"] for case in cases],
        "samples": len(case_evidence),
        "relation_evaluations": relation_count,
        "artifact_identity": list(model_identities.values()),
        "contract_metrics": {
            "signed_effect_contract_consistency": statistics.fmean(sign_hits)
            if sign_hits
            else 0.0,
            "canonical_disagreement_rule_precision": precision,
            "canonical_disagreement_rule_recall": recall,
            "malformed_graph_rejection_rate": malformed_rejections,
            "authority_invariant_pass_rate": statistics.fmean(authority_checks),
            "deterministic_repeatability": deterministic_repeatability,
            "fallback_rate": fallback_count / len(case_evidence),
            "schema_trace_completeness": statistics.fmean(schema_trace_checks),
        },
        "predictive_metrics": {
            "status": "not_evaluated_as_trained_model",
            "causal_generalization": "not_evaluated",
            "held_out_prediction": "not_evaluated",
            "intervention_effect_learning": "not_evaluated",
            "external_multiseed_generalization": "not_evaluated",
            "calibration_ece": _ece(calibration_rows),
            "promotion_eligible": False,
        },
        "resources": {
            "latency_mean_ms": statistics.fmean(latencies_ms),
            "latency_p95_ms": sorted_latencies[p95_index],
            "peak_python_allocation_bytes": peak_ram_bytes,
            "estimated_ram_bytes": estimated_ram_bytes,
            "estimated_vram_bytes": estimated_vram_bytes,
            "bounded_reference_profile": peak_ram_bytes <= 64 * 1024 * 1024
            and estimated_vram_bytes == 0,
        },
        "a_m0": {
            "no_closure_influence": no_closure_influence,
            "no_certification_influence": no_certification_influence,
            "no_state_mutation": no_state_mutation,
            "no_canonical_graph_mutation": no_graph_mutation,
            "no_action_authorization": no_action_authorization,
            "bounded_resource_use": peak_ram_bytes <= 64 * 1024 * 1024
            and estimated_vram_bytes == 0,
            "complete_trace": contract_trace_complete,
        },
        "evidence": case_evidence,
        "operational_influence": "none",
        "evidence_scope": "contract_conformance_only",
    }


def _request(
    graph: Mapping[str, Any], *, repeat_id: int, case_id: str
) -> NeuralInferenceRequest:
    return NeuralInferenceRequest(
        inference_id=f"n4-bench-{case_id}-{repeat_id}",
        run_id="n4-synthetic-benchmark",
        organ="N4",
        capability="causal_prediction",
        payload={"graph": graph, "benchmark_case": case_id},
        seed=repeat_id,
        scope=InferenceScope.LAB,
        resources=ResourceSnapshot(),
    )


def _synthetic_cases() -> list[dict[str, Any]]:
    cases = []

    def add(case_id: str, nodes: list[dict], edges: list[dict], *, conflicts: set[str] | None = None):
        signs = {
            edge["id"]: (-1 if edge["signed_strength"] < 0.0 else 1)
            for edge in edges
            if edge["edge_type"]
            in {"causal_positive", "causal_negative", "counterfactual", "morphism"}
        }
        cases.append(
            {
                "case_id": case_id,
                "graph": _graph(nodes, edges),
                "expected_signs": signs,
                "expected_direction_conflicts": conflicts or set(),
            }
        )

    add(
        "positive_causal_effect",
        [_node("i", "intervention", (1.0, 0.0)), _node("x", "world_variable", (0.0, 1.0))],
        [_edge("positive", "i", "x", "causal_positive", 0.8, canonical=True)],
    )
    add(
        "negative_causal_effect",
        [_node("i", "intervention", (1.0, 0.0)), _node("x", "world_variable", (0.0, 1.0))],
        [_edge("negative", "i", "x", "causal_negative", -0.8, canonical=True)],
    )
    add(
        "causal_chain",
        [
            _node("a", "intervention", (1.0, 0.0)),
            _node("b", "world_variable", (0.5, 0.5)),
            _node("c", "observation", (0.0, 1.0)),
        ],
        [
            _edge("chain-ab", "a", "b", "causal_positive", 0.7, canonical=True),
            _edge("chain-bc", "b", "c", "causal_positive", 0.6, canonical=True),
        ],
    )
    add(
        "collider",
        [
            _node("a", "intervention", (1.0, 0.0)),
            _node("b", "world_variable", (0.0, 1.0)),
            _node("c", "observation", (0.5, 0.5)),
        ],
        [
            _edge("collider-ac", "a", "c", "causal_positive", 0.6, canonical=True),
            _edge("collider-bc", "b", "c", "causal_negative", -0.5, canonical=True),
        ],
    )
    add(
        "confounder_like_ambiguous",
        [
            _node("c", "constraint", (0.5, 0.5)),
            _node("a", "world_variable", (1.0, 0.0)),
            _node("b", "observation", (0.0, 1.0)),
        ],
        [
            _edge("confound-ca", "c", "a", "causal_positive", 0.5, canonical=True),
            _edge("confound-cb", "c", "b", "causal_positive", 0.5, canonical=True),
            _edge("ambiguous-ab", "a", "b", "semantic", 0.2),
        ],
    )
    add(
        "contradiction_edge",
        [_node("i", "intervention", (1.0, 0.0)), _node("x", "world_variable", (0.0, 1.0))],
        [
            _edge("contradicted", "i", "x", "causal_positive", 0.7, canonical=True),
            _edge("contradiction", "i", "x", "contradiction", -0.8),
        ],
    )
    add(
        "missing_canonical_edge",
        [_node("i", "intervention", (1.0, 0.0)), _node("x", "world_variable", (0.0, 1.0))],
        [_edge("missing", "i", "x", "causal_positive", 0.6)],
    )
    add(
        "cross_scenario_morphism",
        [_node("a", "sign", (1.0, 0.0)), _node("b", "sign", (0.0, 1.0), scenario="scenario-b")],
        [_edge("morphism", "a", "b", "morphism", 0.5)],
    )
    add(
        "factual_counterfactual_disagreement",
        [_node("i", "intervention", (1.0, 0.0)), _node("x", "world_variable", (0.0, 1.0))],
        [
            _edge("factual", "i", "x", "causal_positive", 0.8, canonical=True),
            _edge("counterfactual", "i", "x", "counterfactual", -0.8),
        ],
        conflicts={"counterfactual"},
    )
    add(
        "out_of_distribution_pattern",
        [_node("memory", "memory", (1.0, 0.0)), _node("goal", "goal", (0.0, 1.0), scenario="scenario-ood")],
        [_edge("ood-morphism", "memory", "goal", "morphism", -0.4)],
    )
    return cases


def _graph(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "scenario_id": "scenario-a",
        "nodes": nodes,
        "edges": edges,
    }


def _node(
    node_id: str,
    node_type: str,
    features: tuple[float, float],
    *,
    scenario: str = "scenario-a",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_type": node_type,
        "feature_vector": list(features),
        "provenance": "n4-synthetic-benchmark",
        "scenario_id": scenario,
        "timestamp": None,
        "schema_version": GRAPH_SCHEMA_VERSION,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str,
    strength: float,
    *,
    canonical: bool = False,
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "edge_type": edge_type,
        "signed_strength": strength,
        "confidence": 0.9,
        "provenance": "n4-synthetic-benchmark",
        "canonical": canonical,
        "schema_version": GRAPH_SCHEMA_VERSION,
    }


def _measure_malformed_rejection(backend: CausalMessagePassingBackend) -> float:
    base = _synthetic_cases()[0]["graph"]
    malformed = []
    dangling = deepcopy(base)
    dangling["edges"][0]["target"] = "missing"
    malformed.append(dangling)
    unknown = deepcopy(base)
    unknown["nodes"][0]["node_type"] = "unknown"
    malformed.append(unknown)
    mismatch = deepcopy(base)
    mismatch["schema_version"] = "n4-causal-graph-v999"
    malformed.append(mismatch)
    rejected = 0
    for index, graph in enumerate(malformed):
        try:
            backend.infer(_request(graph, repeat_id=0, case_id=f"malformed-{index}"))
        except (TypeError, ValueError):
            rejected += 1
    return rejected / len(malformed)


def _binary_precision_recall(truth: Sequence[bool], predicted: Sequence[bool]) -> tuple[float, float]:
    true_positive = sum(expected and actual for expected, actual in zip(truth, predicted))
    false_positive = sum(not expected and actual for expected, actual in zip(truth, predicted))
    false_negative = sum(expected and not actual for expected, actual in zip(truth, predicted))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    return precision, recall


def _ece(rows: Sequence[tuple[float, float]], *, bins: int = 5) -> float:
    if not rows:
        return 0.0
    total = len(rows)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            row
            for row in rows
            if lower <= row[0] <= upper and (index == bins - 1 or row[0] < upper)
        ]
        if not bucket:
            continue
        confidence = statistics.fmean(row[0] for row in bucket)
        accuracy = statistics.fmean(row[1] for row in bucket)
        error += len(bucket) / total * abs(confidence - accuracy)
    return error
