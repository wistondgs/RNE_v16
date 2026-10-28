"""N4: propuestas causales neuronales tipadas, firmadas y no autoritativas.

El modulo no importa CAU, CTF ni C-GWM y nunca devuelve mutaciones o acciones.
La unica compatibilidad con el contrato N4 v0 queda confinada a fixtures LAB y se
marca explicitamente; toda entrada v1 se valida de forma cerrada.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from ..contracts import (
    AdmissionDecision,
    BackendOutput,
    InferenceScope,
    NeuralInferenceRequest,
    NeuralMode,
    NeuralModelManifest,
)
from ._math import matrix, matvec, sigmoid, tanh_vector, vector


GRAPH_SCHEMA_VERSION = "n4-causal-graph-v1"
OUTPUT_SCHEMA_VERSION = "n4-causal-proposal-v1"
ARTIFACT_SCHEMA_VERSION = "n4-reference-artifact-v1"
LEGACY_ARTIFACT_SCHEMA_VERSION = "n4-reference-artifact-v0"

MAX_NODES_HARD = 512
MAX_EDGES_HARD = 4096
MAX_FEATURE_VALUES_HARD = 16_384
MAX_MESSAGE_PASSING_STEPS = 4


class NodeType(str, Enum):
    WORLD_VARIABLE = "world_variable"
    OBSERVATION = "observation"
    INTERVENTION = "intervention"
    SIGN = "sign"
    EVIDENCE = "evidence"
    MEMORY = "memory"
    GOAL = "goal"
    CONSTRAINT = "constraint"


class EdgeType(str, Enum):
    CAUSAL_POSITIVE = "causal_positive"
    CAUSAL_NEGATIVE = "causal_negative"
    TEMPORAL = "temporal"
    SUPPORT = "support"
    CONTRADICTION = "contradiction"
    COUNTERFACTUAL = "counterfactual"
    SEMANTIC = "semantic"
    MORPHISM = "morphism"


class DisagreementStatus(str, Enum):
    ALIGNED = "aligned"
    WEAK_DISAGREEMENT = "weak_disagreement"
    DIRECTION_CONFLICT = "direction_conflict"
    MISSING_CANONICAL_EDGE = "missing_canonical_edge"
    UNSUPPORTED_PREDICTION = "unsupported_prediction"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


RELATION_EDGE_TYPES = {
    EdgeType.CAUSAL_POSITIVE,
    EdgeType.CAUSAL_NEGATIVE,
    EdgeType.COUNTERFACTUAL,
    EdgeType.MORPHISM,
}
CAUSAL_EDGE_TYPES = {
    EdgeType.CAUSAL_POSITIVE,
    EdgeType.CAUSAL_NEGATIVE,
    EdgeType.COUNTERFACTUAL,
}


def _finite_float(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"n4_{name}_must_be_finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"n4_{name}_must_be_finite")
    return number


def _required_text(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"n4_{name}_required")
    return text


@dataclass(frozen=True, slots=True)
class CausalNode:
    node_id: str
    node_type: NodeType
    feature_vector: tuple[float, ...]
    provenance: str
    scenario_id: str
    timestamp: str | float | None = None
    schema_version: str = GRAPH_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, feature_size: int) -> "CausalNode":
        if str(raw.get("schema_version", "")) != GRAPH_SCHEMA_VERSION:
            raise ValueError("n4_graph_schema_mismatch")
        node_id = _required_text(raw.get("id"), name="node_id")
        try:
            node_type = NodeType(str(raw.get("node_type", "")))
        except ValueError as exc:
            raise ValueError(f"n4_unknown_node_type:{raw.get('node_type')}") from exc
        features = tuple(
            _finite_float(item, name="node_feature")
            for item in vector(raw.get("feature_vector", ()), size=feature_size, name="n4_node_features")
        )
        timestamp = raw.get("timestamp")
        if timestamp is not None and not isinstance(timestamp, (str, int, float)):
            raise ValueError("n4_timestamp_invalid")
        if isinstance(timestamp, (int, float)):
            timestamp = _finite_float(timestamp, name="timestamp")
        return cls(
            node_id=node_id,
            node_type=node_type,
            feature_vector=features,
            provenance=_required_text(raw.get("provenance"), name="node_provenance"),
            scenario_id=_required_text(raw.get("scenario_id"), name="node_scenario_identity"),
            timestamp=timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "node_type": self.node_type.value,
            "feature_vector": list(self.feature_vector),
            "provenance": self.provenance,
            "scenario_id": self.scenario_id,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CausalEdge:
    edge_id: str
    source: str
    target: str
    edge_type: EdgeType
    signed_strength: float
    confidence: float
    provenance: str
    canonical: bool
    schema_version: str = GRAPH_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CausalEdge":
        if str(raw.get("schema_version", "")) != GRAPH_SCHEMA_VERSION:
            raise ValueError("n4_graph_schema_mismatch")
        try:
            edge_type = EdgeType(str(raw.get("edge_type", "")))
        except ValueError as exc:
            raise ValueError(f"n4_unknown_edge_type:{raw.get('edge_type')}") from exc
        strength = _finite_float(raw.get("signed_strength"), name="edge_strength")
        confidence = _finite_float(raw.get("confidence"), name="edge_confidence")
        if not -1.0 <= strength <= 1.0:
            raise ValueError("n4_edge_strength_out_of_range")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("n4_edge_confidence_out_of_range")
        if edge_type is EdgeType.CAUSAL_POSITIVE and strength <= 0.0:
            raise ValueError("n4_unsigned_causal_edge")
        if edge_type is EdgeType.CAUSAL_NEGATIVE and strength >= 0.0:
            raise ValueError("n4_unsigned_causal_edge")
        if edge_type is EdgeType.COUNTERFACTUAL and strength == 0.0:
            raise ValueError("n4_unsigned_causal_edge")
        if not isinstance(raw.get("canonical"), bool):
            raise ValueError("n4_canonical_flag_must_be_boolean")
        return cls(
            edge_id=_required_text(raw.get("id"), name="edge_id"),
            source=_required_text(raw.get("source"), name="edge_source"),
            target=_required_text(raw.get("target"), name="edge_target"),
            edge_type=edge_type,
            signed_strength=strength,
            confidence=confidence,
            provenance=_required_text(raw.get("provenance"), name="edge_provenance"),
            canonical=raw["canonical"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type.value,
            "signed_strength": self.signed_strength,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "canonical": self.canonical,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class TypedCausalGraph:
    scenario_id: str
    nodes: tuple[CausalNode, ...]
    edges: tuple[CausalEdge, ...]
    schema_version: str = GRAPH_SCHEMA_VERSION

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        feature_size: int,
        max_nodes: int = MAX_NODES_HARD,
        max_edges: int = MAX_EDGES_HARD,
    ) -> "TypedCausalGraph":
        if str(raw.get("schema_version", "")) != GRAPH_SCHEMA_VERSION:
            raise ValueError("n4_graph_schema_mismatch")
        scenario_id = _required_text(raw.get("scenario_id"), name="graph_scenario_identity")
        raw_nodes = raw.get("nodes", ())
        raw_edges = raw.get("edges", ())
        if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
            raise ValueError("n4_nodes_must_be_sequence")
        if not isinstance(raw_edges, Sequence) or isinstance(raw_edges, (str, bytes)):
            raise ValueError("n4_edges_must_be_sequence")
        if not raw_nodes:
            raise ValueError("n4_graph_requires_nodes")
        if len(raw_nodes) > min(max_nodes, MAX_NODES_HARD):
            raise ValueError("n4_node_budget_exceeded")
        if len(raw_edges) > min(max_edges, MAX_EDGES_HARD):
            raise ValueError("n4_edge_budget_exceeded")
        if len(raw_nodes) * feature_size > MAX_FEATURE_VALUES_HARD:
            raise ValueError("n4_feature_budget_exceeded")
        nodes = tuple(CausalNode.from_mapping(item, feature_size=feature_size) for item in raw_nodes)
        edges = tuple(CausalEdge.from_mapping(item) for item in raw_edges)
        node_ids = [node.node_id for node in nodes]
        edge_ids = [edge.edge_id for edge in edges]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("n4_duplicate_node_id")
        if len(set(edge_ids)) != len(edge_ids):
            raise ValueError("n4_duplicate_edge_id")
        node_by_id = {node.node_id: node for node in nodes}
        for edge in edges:
            if edge.source not in node_by_id or edge.target not in node_by_id:
                raise ValueError("n4_dangling_edge")
            source_scenario = node_by_id[edge.source].scenario_id
            target_scenario = node_by_id[edge.target].scenario_id
            if source_scenario != target_scenario and edge.edge_type is not EdgeType.MORPHISM:
                raise ValueError("n4_inconsistent_scenario_identity")
        foreign_nodes = {node.node_id for node in nodes if node.scenario_id != scenario_id}
        morphism_nodes = {
            endpoint
            for edge in edges
            if edge.edge_type is EdgeType.MORPHISM
            for endpoint in (edge.source, edge.target)
        }
        if not foreign_nodes.issubset(morphism_nodes):
            raise ValueError("n4_inconsistent_scenario_identity")
        return cls(scenario_id=scenario_id, nodes=nodes, edges=edges)

    @property
    def graph_hash(self) -> str:
        payload = {
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class CausalMessagePassingBackend:
    """Backend CPU compacto para validar el contrato; no es un modelo entrenado."""

    def __init__(self) -> None:
        self._weights: dict[str, Any] | None = None

    def load_frozen_reference_contract(self) -> None:
        """Carga una referencia CPU embebida, sin artefacto ni claim de entrenamiento.

        Esta ruta existe para ejercitar el mismo contrato tipado en la frontera viva
        cuando no hay pesos certificados. No descarga, no aprende y no representa un
        modelo causal entrenado.
        """

        identity = {
            "classification": "reference",
            "trained": False,
            "frozen": True,
            "experimental": True,
            "contract": ARTIFACT_SCHEMA_VERSION,
        }
        model_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self._weights = {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "input_size": 4,
            "hidden_size": 4,
            "input": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "message": [
                [0.5, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.0],
                [0.0, 0.0, 0.5, 0.0],
                [0.0, 0.0, 0.0, 0.5],
            ],
            "update": [
                [0.5, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.0],
                [0.0, 0.0, 0.5, 0.0],
                [0.0, 0.0, 0.0, 0.5],
            ],
            "output": [
                [0.5, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.0],
                [0.0, 0.0, 0.5, 0.0],
                [0.0, 0.0, 0.0, -0.5],
            ],
            "model_kind": "reference",
            "trained": False,
            "frozen": True,
            "experimental": True,
            "model_id": "n4-frozen-contract-reference",
            "model_version": "1",
            "model_hash": model_hash,
            "manifest_hash": model_hash,
            "max_nodes": 32,
            "max_edges": 64,
            "steps": 2,
            "supported_nodes": frozenset(item.value for item in NodeType),
            "supported_edges": frozenset(item.value for item in EdgeType),
        }

    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None:
        if device != "cpu" or manifest.organ != "N4":
            raise ValueError("n4_reference_backend_requires_cpu_n4_manifest")
        with open(artifact_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        artifact_schema = str(raw.get("artifact_schema_version", LEGACY_ARTIFACT_SCHEMA_VERSION))
        if artifact_schema not in {ARTIFACT_SCHEMA_VERSION, LEGACY_ARTIFACT_SCHEMA_VERSION}:
            raise ValueError("n4_artifact_schema_mismatch")
        input_size = int(raw["input_size"])
        hidden_size = int(raw["hidden_size"])
        if input_size <= 0 or hidden_size <= 0:
            raise ValueError("n4_model_dimensions_must_be_positive")
        model_kind = str(raw.get("model_kind", "reference"))
        trained = bool(raw.get("trained", False))
        frozen = bool(raw.get("frozen", True))
        experimental = bool(raw.get("experimental", True))
        if model_kind not in {"reference", "trained"}:
            raise ValueError("n4_model_kind_invalid")
        if model_kind == "reference" and trained:
            raise ValueError("n4_reference_model_cannot_claim_trained")
        if model_kind == "trained" and not raw.get("training_evidence"):
            raise ValueError("n4_trained_model_requires_training_evidence")
        output = matrix(raw["output_weight"], columns=hidden_size, name="output_weight")
        if artifact_schema == ARTIFACT_SCHEMA_VERSION and len(output) < 4:
            raise ValueError("n4_separate_uncertainty_head_required")
        max_nodes = min(max(1, int(raw.get("max_nodes", 128))), MAX_NODES_HARD)
        max_edges = min(max(1, int(raw.get("max_edges", 512))), MAX_EDGES_HARD)
        steps = min(max(1, int(raw.get("message_passing_steps", 3))), MAX_MESSAGE_PASSING_STEPS)
        supported_nodes = _validated_enum_values(
            raw.get("supported_node_types", [item.value for item in NodeType]), NodeType, "node"
        )
        supported_edges = _validated_enum_values(
            raw.get("supported_edge_types", [item.value for item in EdgeType]), EdgeType, "edge"
        )
        weights = {
            "artifact_schema_version": artifact_schema,
            "input_size": input_size,
            "hidden_size": hidden_size,
            "input": matrix(raw["input_weight"], columns=input_size, name="input_weight"),
            "message": matrix(raw["message_weight"], columns=hidden_size, name="message_weight"),
            "update": matrix(raw["update_weight"], columns=hidden_size, name="update_weight"),
            "output": output,
            "model_kind": model_kind,
            "trained": trained,
            "frozen": frozen,
            "experimental": experimental,
            "model_id": manifest.model_id,
            "model_version": manifest.version,
            "model_hash": manifest.artifact_sha256,
            "manifest_hash": manifest.manifest_sha256,
            "max_nodes": max_nodes,
            "max_edges": max_edges,
            "steps": steps,
            "supported_nodes": supported_nodes,
            "supported_edges": supported_edges,
        }
        if any(len(weights[name]) != hidden_size for name in ("input", "message", "update")):
            raise ValueError("n4_hidden_shape_mismatch")
        for name in ("input", "message", "update", "output"):
            for row in weights[name]:
                for value in row:
                    _finite_float(value, name=f"{name}_weight")
        self._weights = weights

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        if self._weights is None:
            raise RuntimeError("backend_not_loaded")
        raw_graph = request.payload.get("graph", request.payload)
        if not isinstance(raw_graph, Mapping):
            raise ValueError("n4_graph_must_be_mapping")
        if str(raw_graph.get("schema_version", "")) != GRAPH_SCHEMA_VERSION:
            return self._infer_legacy_lab(request)
        graph = TypedCausalGraph.from_mapping(
            raw_graph,
            feature_size=self._weights["input_size"],
            max_nodes=self._weights["max_nodes"],
            max_edges=self._weights["max_edges"],
        )
        states = self._message_pass(graph)
        relations = [
            self._predict_relation(edge, graph, states)
            for edge in graph.edges
            if edge.edge_type in RELATION_EDGE_TYPES
        ]
        fallback_required = not relations or all(item["insufficient_evidence"] for item in relations)
        confidence = sum(item["confidence"] for item in relations) / len(relations) if relations else 0.0
        uncertainty = sum(item["uncertainty"] for item in relations) / len(relations) if relations else 1.0
        candidate = {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "input_graph_hash": graph.graph_hash,
            "scenario_id": graph.scenario_id,
            "relations": relations,
            "model": self._model_identity(),
            "authority": {
                "proposal_only": True,
                "may_mutate_graph": False,
                "may_choose_intervention": False,
                "may_authorize_action": False,
                "authoritative_systems": ["CAU", "CTF", "C-GWM", "LOTF", "DED"],
            },
            "fallback": {
                "required": fallback_required,
                "route": "deterministic_causal_authorities",
                "reason": "insufficient_evidence" if fallback_required else None,
            },
        }
        return BackendOutput(
            candidate_output=candidate,
            confidence=confidence,
            uncertainty=uncertainty,
            cost=self._resource_cost(graph),
            trace=tuple(
                {
                    "relation_id": item["relation_id"],
                    "disagreement": item["canonical_disagreement"]["status"],
                    "ood": item["ood"],
                }
                for item in relations
            ),
        )

    def _message_pass(self, graph: TypedCausalGraph) -> dict[str, list[float]]:
        assert self._weights is not None
        states = {
            node.node_id: tanh_vector(matvec(self._weights["input"], node.feature_vector))
            for node in graph.nodes
        }
        for _ in range(self._weights["steps"]):
            incoming = {node_id: [0.0] * self._weights["hidden_size"] for node_id in states}
            for edge in graph.edges:
                typed_sign = _edge_message_sign(edge)
                message = matvec(self._weights["message"], states[edge.source])
                factor = typed_sign * abs(edge.signed_strength) * edge.confidence
                incoming[edge.target] = [
                    current + factor * value for current, value in zip(incoming[edge.target], message)
                ]
            states = {
                node_id: tanh_vector(
                    [
                        prior + message
                        for prior, message in zip(
                            matvec(self._weights["update"], state), incoming[node_id]
                        )
                    ]
                )
                for node_id, state in states.items()
            }
        return states

    def _predict_relation(
        self,
        edge: CausalEdge,
        graph: TypedCausalGraph,
        states: Mapping[str, Sequence[float]],
    ) -> dict[str, Any]:
        assert self._weights is not None
        combined = [
            (source + target) / 2.0
            for source, target in zip(states[edge.source], states[edge.target])
        ]
        heads = matvec(self._weights["output"], combined)
        direction = -1.0 if edge.signed_strength < 0.0 else 1.0
        magnitude = math.tanh(abs(edge.signed_strength) + 0.25 * abs(math.tanh(heads[1])))
        signed_effect = direction * magnitude
        base_confidence = sigmoid(heads[2]) * edge.confidence if len(heads) > 2 else 0.5 * edge.confidence
        independent_uncertainty = sigmoid(heads[3]) if len(heads) > 3 else sigmoid(-abs(heads[2]))
        node_by_id = {node.node_id: node for node in graph.nodes}
        ood_reasons = []
        if node_by_id[edge.source].node_type.value not in self._weights["supported_nodes"]:
            ood_reasons.append("source_node_pattern")
        if node_by_id[edge.target].node_type.value not in self._weights["supported_nodes"]:
            ood_reasons.append("target_node_pattern")
        if edge.edge_type.value not in self._weights["supported_edges"]:
            ood_reasons.append("edge_pattern")
        if node_by_id[edge.source].scenario_id != node_by_id[edge.target].scenario_id:
            ood_reasons.append("cross_scenario_pattern")
        ood = bool(ood_reasons)
        uncertainty = max(independent_uncertainty, 0.85) if ood else independent_uncertainty
        confidence = min(base_confidence, 0.15) if ood else base_confidence
        supporting_edges = _supporting_edge_ids(edge, graph.edges)
        insufficient = bool(ood or confidence < 0.20 or uncertainty > 0.80)
        disagreement = _canonical_disagreement(
            edge,
            graph.edges,
            signed_effect=signed_effect,
            uncertainty=uncertainty,
            insufficient_evidence=insufficient,
            supporting_edge_ids=supporting_edges,
        )
        next_mean = math.tanh(heads[0] + signed_effect)
        width = min(1.0, max(0.01, uncertainty))
        return {
            "relation_id": f"n4:{edge.edge_id}",
            "source_node_id": edge.source,
            "target_node_id": edge.target,
            "relation_edge_id": edge.edge_id,
            "signed_expected_effect": signed_effect,
            "magnitude": abs(signed_effect),
            "uncertainty": uncertainty,
            "confidence": confidence,
            "next_state_bounded_estimate": {
                "lower": max(-1.0, next_mean - width),
                "mean": next_mean,
                "upper": min(1.0, next_mean + width),
            },
            "supporting_node_ids": [edge.source, edge.target],
            "supporting_edge_ids": supporting_edges,
            "canonical_disagreement": disagreement,
            "ood": ood,
            "ood_reasons": ood_reasons,
            "insufficient_evidence": insufficient,
            "model_identity": self._model_identity(),
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
        }

    def _model_identity(self) -> dict[str, Any]:
        assert self._weights is not None
        return {
            "model_id": self._weights["model_id"],
            "version": self._weights["model_version"],
            "model_hash": self._weights["model_hash"],
            "manifest_hash": self._weights["manifest_hash"],
            "classification": self._weights["model_kind"],
            "trained": self._weights["trained"],
            "frozen": self._weights["frozen"],
            "experimental": self._weights["experimental"],
            "artifact_schema_version": self._weights["artifact_schema_version"],
        }

    def _resource_cost(self, graph: TypedCausalGraph) -> dict[str, Any]:
        assert self._weights is not None
        values = len(graph.nodes) * self._weights["hidden_size"]
        weights = sum(
            len(row)
            for name in ("input", "message", "update", "output")
            for row in self._weights[name]
        )
        return {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "layers": self._weights["steps"],
            "estimated_ram_bytes": 8 * (values + weights),
            "estimated_vram_bytes": 0,
            "backend_device": "cpu",
        }

    def _infer_legacy_lab(self, request: NeuralInferenceRequest) -> BackendOutput:
        """Compatibilidad de fixture v0; nunca se acepta en frontera LIVE."""
        assert self._weights is not None
        if request.scope is not InferenceScope.LAB:
            raise ValueError("n4_graph_schema_mismatch")
        if self._weights["artifact_schema_version"] != LEGACY_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("n4_graph_schema_mismatch")
        raw_nodes = request.payload.get("nodes", ())
        raw_edges = request.payload.get("edges", ())
        nodes: dict[str, list[float]] = {}
        for item in raw_nodes:
            node_id = _required_text(item.get("id"), name="node_id")
            if node_id in nodes:
                raise ValueError("n4_duplicate_node_id")
            nodes[node_id] = tanh_vector(
                matvec(
                    self._weights["input"],
                    vector(item.get("features", ()), size=self._weights["input_size"]),
                )
            )
        if not nodes:
            raise ValueError("n4_graph_requires_nodes")
        for _ in range(self._weights["steps"]):
            incoming = {node_id: [0.0] * self._weights["hidden_size"] for node_id in nodes}
            for edge in raw_edges:
                source, target = str(edge.get("source", "")), str(edge.get("target", ""))
                if source not in nodes or target not in nodes:
                    raise ValueError("n4_dangling_edge")
                strength = _finite_float(edge.get("strength", 1.0), name="edge_strength")
                message = matvec(self._weights["message"], nodes[source])
                incoming[target] = [a + strength * b for a, b in zip(incoming[target], message)]
            nodes = {
                node_id: tanh_vector(
                    [a + b for a, b in zip(matvec(self._weights["update"], state), incoming[node_id])]
                )
                for node_id, state in nodes.items()
            }
        predictions = {}
        for node_id, state in nodes.items():
            values = matvec(self._weights["output"], state)
            confidence = sigmoid(values[2]) if len(values) > 2 else 0.5
            predictions[node_id] = {
                "next_state": sigmoid(values[0]),
                "intervention_effect": math.tanh(values[1]) if len(values) > 1 else 0.0,
                "edge_confidence": confidence,
                "uncertainty": sigmoid(-abs(values[2])) if len(values) > 2 else 0.5,
            }
        confidence = sum(item["edge_confidence"] for item in predictions.values()) / len(predictions)
        return BackendOutput(
            candidate_output={
                "predictions": predictions,
                "input_compatibility": "legacy_reference_v0",
                "model": self._model_identity(),
                "authority": "CAU+CTF+C-GWM",
            },
            confidence=confidence,
            uncertainty=1.0 - confidence,
            cost={"nodes": len(nodes), "edges": len(raw_edges), "layers": self._weights["steps"]},
        )

    def unload(self) -> None:
        self._weights = None


class CausalPredictionAdmission:
    """Admite solo trazas shadow; nunca decisiones, acciones ni mutaciones."""

    def __call__(self, candidate: Any, request: NeuralInferenceRequest) -> AdmissionDecision:
        if not isinstance(candidate, Mapping):
            return AdmissionDecision(False, reason="n4_prediction_schema_invalid")
        if candidate.get("input_compatibility") == "legacy_reference_v0":
            if request.scope is not InferenceScope.LAB or _contains_forbidden_authority_output(
                candidate
            ):
                return AdmissionDecision(False, reason="n4_legacy_contract_lab_only")
            if not isinstance(candidate.get("predictions"), Mapping):
                return AdmissionDecision(False, reason="n4_prediction_schema_invalid")
            return AdmissionDecision(
                True,
                output={
                    "predictions": candidate["predictions"],
                    "authority": "CAU+CTF+C-GWM",
                    "admission_scope": "lab_shadow_logging_only",
                },
                reason="n4_legacy_reference_shadow_only",
                effective_mode_ceiling=NeuralMode.SHADOW,
            )
        if _contains_forbidden_authority_output(candidate):
            return AdmissionDecision(False, reason="n4_forbidden_authority_output")
        if candidate.get("schema_version") != OUTPUT_SCHEMA_VERSION:
            return AdmissionDecision(False, reason="n4_prediction_schema_invalid")
        if candidate.get("graph_schema_version") != GRAPH_SCHEMA_VERSION:
            return AdmissionDecision(False, reason="n4_graph_schema_mismatch")
        authority = candidate.get("authority")
        if not isinstance(authority, Mapping) or not bool(authority.get("proposal_only")):
            return AdmissionDecision(False, reason="n4_authority_contract_missing")
        if any(
            bool(authority.get(field))
            for field in ("may_mutate_graph", "may_choose_intervention", "may_authorize_action")
        ):
            return AdmissionDecision(False, reason="n4_forbidden_authority_output")
        relations = candidate.get("relations")
        if not isinstance(relations, list):
            return AdmissionDecision(False, reason="n4_relations_must_be_list")
        fallback = candidate.get("fallback")
        if not isinstance(fallback, Mapping):
            return AdmissionDecision(False, reason="n4_fallback_contract_missing")
        if not relations or bool(fallback.get("required")):
            return AdmissionDecision(False, reason="n4_insufficient_evidence_fallback")
        try:
            input_graph_hash = _required_text(
                candidate.get("input_graph_hash"), name="input_graph_hash"
            )
            if len(input_graph_hash) != 64 or any(
                character not in "0123456789abcdef" for character in input_graph_hash
            ):
                raise ValueError("input_graph_hash_invalid")
            scenario_id = _required_text(candidate.get("scenario_id"), name="scenario_id")
            model = candidate.get("model")
            if not isinstance(model, Mapping) or not model.get("model_hash"):
                raise ValueError("model_identity_missing")
            for relation in relations:
                _validate_relation_output(relation)
        except (TypeError, ValueError) as exc:
            return AdmissionDecision(False, reason=f"n4_relation_output_invalid:{exc}")
        conflicts = [
            item["relation_id"]
            for item in relations
            if item["canonical_disagreement"]["status"] == DisagreementStatus.DIRECTION_CONFLICT.value
        ]
        confidence = min(float(item["confidence"]) for item in relations)
        if conflicts:
            confidence = min(confidence, 0.25)
        return AdmissionDecision(
            True,
            output={
                "schema_version": OUTPUT_SCHEMA_VERSION,
                "input_graph_hash": input_graph_hash,
                "scenario_id": scenario_id,
                "relations": relations,
                "model": model,
                "admission_scope": "shadow_logging_only",
                "confidence_after_disagreement_gate": confidence,
                "direction_conflicts": conflicts,
                "authority": {
                    "proposal_only": True,
                    "authoritative_systems": ["CAU", "CTF", "C-GWM", "LOTF", "DED"],
                },
            },
            reason="n4_typed_prediction_shadow_only",
            effective_mode_ceiling=NeuralMode.SHADOW,
        )


def _validated_enum_values(raw: Any, enum_type: type[Enum], label: str) -> frozenset[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"n4_supported_{label}_types_must_be_sequence")
    valid = {item.value for item in enum_type}
    values = {str(item) for item in raw}
    unknown = values - valid
    if unknown:
        raise ValueError(f"n4_unknown_supported_{label}_type:{sorted(unknown)[0]}")
    return frozenset(values)


_FORBIDDEN_AUTHORITY_OUTPUTS = frozenset(
    {
        "action",
        "authorization",
        "certificate",
        "closure_decision",
        "effective_output",
        "graph_mutations",
        "selected_intervention",
    }
)


def _contains_forbidden_authority_output(candidate: Mapping[str, Any]) -> bool:
    return not _FORBIDDEN_AUTHORITY_OUTPUTS.isdisjoint(candidate)


def _edge_message_sign(edge: CausalEdge) -> float:
    if edge.edge_type in {EdgeType.CAUSAL_NEGATIVE, EdgeType.CONTRADICTION}:
        return -1.0
    if edge.edge_type is EdgeType.COUNTERFACTUAL:
        return -1.0 if edge.signed_strength < 0.0 else 1.0
    return 1.0 if edge.signed_strength >= 0.0 else -1.0


def _supporting_edge_ids(relation: CausalEdge, edges: Sequence[CausalEdge]) -> list[str]:
    supporting = {relation.edge_id}
    for edge in edges:
        if edge.edge_type in {EdgeType.SUPPORT, EdgeType.CONTRADICTION}:
            if edge.source in {relation.source, relation.target} or edge.target in {
                relation.source,
                relation.target,
            }:
                supporting.add(edge.edge_id)
    return sorted(supporting)


def _canonical_disagreement(
    relation: CausalEdge,
    edges: Sequence[CausalEdge],
    *,
    signed_effect: float,
    uncertainty: float,
    insufficient_evidence: bool,
    supporting_edge_ids: Sequence[str],
) -> dict[str, Any]:
    canonical = [
        edge
        for edge in edges
        if edge.canonical
        and edge.edge_type in CAUSAL_EDGE_TYPES
        and edge.source == relation.source
        and edge.target == relation.target
    ]
    contradiction = any(
        edge.edge_type is EdgeType.CONTRADICTION and edge.edge_id in supporting_edge_ids
        for edge in edges
    )
    canonical_ids = [edge.edge_id for edge in canonical]
    canonical_directions = {-1 if edge.signed_strength < 0.0 else 1 for edge in canonical}
    predicted_direction = -1 if signed_effect < 0.0 else 1
    if canonical and predicted_direction not in canonical_directions:
        status = DisagreementStatus.DIRECTION_CONFLICT
        reason = "predicted_direction_opposes_canonical_signature"
    elif insufficient_evidence:
        status = DisagreementStatus.INSUFFICIENT_EVIDENCE
        reason = "ood_or_uncertainty_prevents_canonical_comparison"
    elif relation.canonical and relation.edge_id in canonical_ids and not contradiction:
        status = DisagreementStatus.ALIGNED
        reason = "prediction_follows_canonical_direction"
    elif canonical:
        if contradiction or min(abs(abs(edge.signed_strength) - abs(signed_effect)) for edge in canonical) > 0.40:
            status = DisagreementStatus.WEAK_DISAGREEMENT
            reason = "direction_aligned_but_evidence_or_magnitude_differs"
        else:
            status = DisagreementStatus.ALIGNED
            reason = "prediction_aligned_with_canonical_signature"
    elif relation.edge_type in {EdgeType.COUNTERFACTUAL, EdgeType.MORPHISM} and len(supporting_edge_ids) <= 1:
        status = DisagreementStatus.UNSUPPORTED_PREDICTION
        reason = "relation_has_no_independent_supporting_edge"
    else:
        status = DisagreementStatus.MISSING_CANONICAL_EDGE
        reason = "no_canonical_signature_for_relation"
    return {
        "status": status.value,
        "reason": reason,
        "canonical_edge_ids": canonical_ids,
        "direction_conflict": status is DisagreementStatus.DIRECTION_CONFLICT,
        "uncertainty_at_comparison": uncertainty,
    }


def _validate_relation_output(raw: Any) -> None:
    if not isinstance(raw, Mapping):
        raise ValueError("relation_must_be_mapping")
    for name in (
        "relation_id",
        "source_node_id",
        "target_node_id",
        "relation_edge_id",
        "graph_schema_version",
    ):
        _required_text(raw.get(name), name=name)
    if raw["graph_schema_version"] != GRAPH_SCHEMA_VERSION:
        raise ValueError("graph_schema_mismatch")
    effect = _finite_float(raw.get("signed_expected_effect"), name="signed_effect")
    magnitude = _finite_float(raw.get("magnitude"), name="magnitude")
    uncertainty = _finite_float(raw.get("uncertainty"), name="uncertainty")
    confidence = _finite_float(raw.get("confidence"), name="confidence")
    if not -1.0 <= effect <= 1.0 or not 0.0 <= magnitude <= 1.0:
        raise ValueError("effect_out_of_range")
    if not math.isclose(abs(effect), magnitude, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("effect_magnitude_mismatch")
    if not 0.0 <= uncertainty <= 1.0 or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence_or_uncertainty_out_of_range")
    estimate = raw.get("next_state_bounded_estimate")
    if not isinstance(estimate, Mapping):
        raise ValueError("next_state_estimate_missing")
    lower = _finite_float(estimate.get("lower"), name="next_state_lower")
    mean = _finite_float(estimate.get("mean"), name="next_state_mean")
    upper = _finite_float(estimate.get("upper"), name="next_state_upper")
    if not -1.0 <= lower <= mean <= upper <= 1.0:
        raise ValueError("next_state_bounds_invalid")
    if not isinstance(raw.get("supporting_node_ids"), list) or not raw["supporting_node_ids"]:
        raise ValueError("supporting_nodes_missing")
    if not isinstance(raw.get("supporting_edge_ids"), list) or not raw["supporting_edge_ids"]:
        raise ValueError("supporting_edges_missing")
    disagreement = raw.get("canonical_disagreement")
    if not isinstance(disagreement, Mapping):
        raise ValueError("canonical_disagreement_missing")
    DisagreementStatus(str(disagreement.get("status", "")))
    model = raw.get("model_identity")
    if not isinstance(model, Mapping) or not model.get("model_hash"):
        raise ValueError("model_identity_missing")
