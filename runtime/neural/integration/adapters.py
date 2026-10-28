"""Adaptadores canónicos N1-N6 para la frontera simbiótica viva.

Cada adaptador llama el módulo dueño del órgano o una política de referencia
declarada. Ninguno selecciona acciones, certifica, muta grafos ni promociona memoria.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from runtime.neural.contracts import BackendOutput, NeuralInferenceRequest, NeuralMode
from runtime.neural.organs.n4_causal import (
    GRAPH_SCHEMA_VERSION,
    CausalMessagePassingBackend,
    CausalPredictionAdmission,
)
from runtime.neural.organs.n3_temporal import TemporalMemoryAdmission
from runtime.neural.organs.n5_ingest import DeterministicChunker, HNetBoundaryAdmission

from .contracts import SymbiosisIdentity, canonical_json_bytes


OPTIONAL_FAMILIES = ("IND", "PLAN", "OPT", "NESY", "IMAGINATION", "EVO_SEARCH")


class CanonicalOrganAdapter(Protocol):
    organ: str
    capability: str
    authority_ceiling: NeuralMode
    consumer: str
    reference_id: str
    admission_gate: Any

    def infer(
        self, request: NeuralInferenceRequest, context: Mapping[str, Any]
    ) -> BackendOutput: ...

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class N1ReferencePolicy:
    """Política contextual determinista; no se presenta como MLP entrenado."""

    min_utility: float = 0.25
    max_families: int = 2

    def evaluate(self, inputs: Mapping[str, Any], temporal: Mapping[str, Any]) -> BackendOutput:
        observation = inputs.get("observation") or {}
        resources = inputs.get("resources") or {}
        alarm = bool(observation.get("alarm"))
        # Sin `or 1.0`: una incertidumbre MEDIDA de 0.0 —certeza perfecta— se
        # leía como 1.0, incertidumbre total. Invierte el sentido del dato.
        _u = temporal.get("uncertainty")
        uncertainty = 1.0 if _u is None else float(_u)
        pressure = max(
            float(resources.get("cpu_pressure", 0.0) or 0.0),
            float(resources.get("memory_pressure", 0.0) or 0.0),
            float(resources.get("thermal_pressure", 0.0) or 0.0),
        )
        ranked = []
        for family in OPTIONAL_FAMILIES:
            score = {
                "IND": 0.25 + 0.20 * bool(inputs.get("memory_hits")),
                "PLAN": 0.35 + 0.30 * alarm,
                "OPT": 0.30 + 0.20 * alarm,
                "NESY": 0.35 + 0.20 * uncertainty,
                "IMAGINATION": 0.20 + 0.25 * alarm,
                "EVO_SEARCH": 0.15 + 0.10 * alarm,
            }[family]
            score -= 0.45 * pressure
            ranked.append({"family": family, "score": round(score, 6)})
        ranked.sort(key=lambda row: (-row["score"], row["family"]))
        proposed = [
            row["family"] for row in ranked if row["score"] > self.min_utility
        ][: self.max_families]
        decision = "ACTIVATE" if proposed else "ABSTAIN"
        return BackendOutput(
            candidate_output={
                "status": "ok" if proposed else "abstained",
                "backend": "n1_reference_policy",
                "classification": "reference",
                "trained_model": False,
                "activation": {"decision": decision, "families": proposed},
                "proposed_families": proposed,
                "ranked": ranked,
                "features": {
                    "alarm": alarm,
                    "uncertainty": uncertainty,
                    "resource_pressure": pressure,
                    "memory_count": len(inputs.get("memory_hits", [])),
                },
                "scheduler_authority": True,
            },
            confidence=max([row["score"] for row in ranked], default=0.0),
            uncertainty=uncertainty,
            cost={"families_scored": len(ranked), "ram_mb": 0.05, "vram_mb": 0.0},
        )


class N1Adapter:
    organ = "N1"
    capability = "family_routing_proposal"
    authority_ceiling = NeuralMode.SHADOW
    consumer = "MetaSchedulerComparator"
    reference_id = "rnfe:N1:family_routing_proposal:reference-policy-v1"
    admission_gate = None

    def __init__(self) -> None:
        self.policy = N1ReferencePolicy()

    def infer(self, request: NeuralInferenceRequest, context: Mapping[str, Any]) -> BackendOutput:
        return self.policy.evaluate(context["inputs"], context.get("n3_temporal") or {})

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]:
        return {"status": "disabled", "proposed_families": []}


class N2Adapter:
    organ = "N2"
    capability = "semantic_neurosymbolic_candidate"
    authority_ceiling = NeuralMode.SHADOW
    consumer = "DED+LOT-F+NESY"
    reference_id = "rnfe:N2:semantic_neurosymbolic_candidate:nesy-v1"
    admission_gate = None

    def infer(self, request: NeuralInferenceRequest, context: Mapping[str, Any]) -> BackendOutput:
        from runtime.reasoning.families import nesy

        state = dict(context.get("reasoning_state") or {})
        inputs = context["inputs"]
        lotf_valid = bool(context.get("lotf_valid"))
        nesy_result = nesy.execute({**state, "_symbiotic_n2_verify": True})
        nesy_delta = dict(nesy_result.get("state_delta") or {})
        ded_verified = bool(state.get("ded_validated"))
        nesy_verified = bool(nesy_delta.get("nesy_coherent"))
        verified = ded_verified and lotf_valid and nesy_verified
        verdict = "accepted_as_shadow_evidence" if verified else "rejected_by_symbolic_verifier"
        return BackendOutput(
            candidate_output={
                "status": "ok",
                "proposition": str(state.get("ded_conclusion") or inputs.get("formula") or ""),
                "verified": verified,
                "verdict": verdict,
                "verification": {"DED": ded_verified, "LOT-F": lotf_valid, "NESY": nesy_verified},
                "nesy": nesy_result,
                "authority": "DED+LOT-F+NESY",
            },
            confidence=float(nesy_result.get("confidence", 0.0) or 0.0),
            uncertainty=0.0 if verified else 1.0,
            cost={"verifiers": 3, "ram_mb": 0.05, "vram_mb": 0.0},
        )

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]:
        return {"status": "disabled", "verified": False}


class N3Adapter:
    organ = "N3"
    capability = "temporal_reference_state"
    authority_ceiling = NeuralMode.PROVISIONAL
    consumer = "next_episode+MFM+continuity"
    reference_id = "rnfe:N3:temporal_reference_state:reference-filter-v1"
    # Cableada. N3 tiene techo PROVISIONAL desde siempre y su puerta estaba
    # escrita (`n3_temporal.py:64`) y sin conectar, así que el órgano alcanzaba
    # el modo con autoridad y nadie le preguntaba a la puerta: salía con
    # influence=NONE y sin registrar razón. La puerta valida el esquema de
    # salida y devuelve una propuesta ACOTADA; sin ella el techo no servía.
    admission_gate = TemporalMemoryAdmission()

    def __init__(self) -> None:
        self._states: dict[tuple[str, str, str], dict[str, Any]] = {}

    @staticmethod
    def state_key(identity: SymbiosisIdentity) -> tuple[str, str, str]:
        return (identity.organism_id, identity.scenario_id, identity.lineage_id)

    def infer(self, request: NeuralInferenceRequest, context: Mapping[str, Any]) -> BackendOutput:
        identity: SymbiosisIdentity = context["identity"]
        inputs = context["inputs"]
        key = self.state_key(identity)
        observation = inputs.get("observation") or {}
        metadata = inputs.get("scenario_metadata") or {}
        raw_variable = metadata.get("main_variable")
        main_variable = str(raw_variable).strip() if raw_variable is not None else ""
        default_source = metadata.get("main_variable_default_source")
        value = _number(observation.get(main_variable)) if main_variable else None
        measurement_status = "measured" if value is not None else (
            "not_applicable" if not main_variable else "unmeasured"
        )
        if value is None and default_source:
            value = _number(metadata.get("main_variable_default"))
            if value is not None:
                measurement_status = "defaulted"
        previous = self._states.get(key)
        previous_value = _number((previous or {}).get("last_measured_value"))
        trend = (
            value - previous_value
            if value is not None and previous_value is not None
            else None
        )
        count = int((previous or {}).get("episode_count", 0)) + 1
        measurement_count = int((previous or {}).get("measurement_count", 0))
        if measurement_status in {"measured", "defaulted"}:
            measurement_count += 1
        last_measured_value = (
            value
            if measurement_status in {"measured", "defaulted"}
            else previous_value
        )
        uncertainty = 1.0 / (measurement_count + 1.0) if measurement_count else 1.0
        summary = (
            f"{main_variable}={value:.6f};trend="
            f"{trend:+.6f};measurements={measurement_count}"
            if value is not None and trend is not None
            else f"{main_variable or 'not_applicable'}={measurement_status};"
            f"measurements={measurement_count}"
        )
        state = {
            "status": "ok",
            "backend": "reference_temporal_filter",
            "classification": "reference",
            "mamba2_active": False,
            "state_key": list(key),
            "previous_state": previous,
            "value": value,
            "trend": trend,
            "measurement_status": measurement_status,
            "default_source": str(default_source) if default_source else None,
            "last_measured_value": last_measured_value,
            "uncertainty": uncertainty,
            "episode_count": count,
            "measurement_count": measurement_count,
            "provenance": identity.episode_id,
            "version": "reference-temporal-v1",
            "summary": summary,
        }
        self._states[key] = state
        return BackendOutput(
            candidate_output=state,
            confidence=1.0 - state["uncertainty"],
            uncertainty=state["uncertainty"],
            cost={"state_entries": len(self._states), "ram_mb": 0.1, "vram_mb": 0.0},
        )

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]:
        return {"status": "disabled", "state_key": list(self.state_key(identity))}

    def export_state(self) -> dict[str, Any]:
        return {
            "schema_version": "n3-temporal-checkpoint-v1",
            "entries": [
                {"state_key": list(key), "state": dict(state)}
                for key, state in sorted(self._states.items())
            ],
        }

    def restore_state(self, payload: Mapping[str, Any] | None) -> int:
        data = dict(payload or {})
        if data.get("schema_version") != "n3-temporal-checkpoint-v1":
            return 0
        restored = 0
        for item in data.get("entries") or []:
            if not isinstance(item, Mapping):
                continue
            raw_key, raw_state = item.get("state_key"), item.get("state")
            if (
                not isinstance(raw_key, (list, tuple))
                or len(raw_key) != 3
                or not all(str(value or "").strip() for value in raw_key)
                or not isinstance(raw_state, Mapping)
            ):
                continue
            key = tuple(str(value) for value in raw_key)
            state = dict(raw_state)
            if list(key) != list(state.get("state_key") or []):
                continue
            self._states[key] = state
            restored += 1
        return restored


class N4Adapter:
    organ = "N4"
    capability = "typed_causal_proposal"
    authority_ceiling = NeuralMode.SHADOW
    consumer = "CAU+CTF+C-GWM comparator"
    reference_id = "rnfe:N4:typed_causal_proposal:frozen-contract-v1"
    admission_gate = CausalPredictionAdmission()

    def __init__(self) -> None:
        self.backend = CausalMessagePassingBackend()
        self.backend.load_frozen_reference_contract()

    def infer(self, request: NeuralInferenceRequest, context: Mapping[str, Any]) -> BackendOutput:
        identity: SymbiosisIdentity = context["identity"]
        graph, evidence = self._graph(identity, context["inputs"])
        graph_request = NeuralInferenceRequest(
            inference_id=request.inference_id,
            run_id=request.run_id,
            organ=request.organ,
            capability=request.capability,
            payload={"graph": graph},
            seed=request.seed,
            scope=request.scope,
            resources=request.resources,
            causal_context=request.causal_context,
        )
        output = self.backend.infer(graph_request)
        candidate = dict(output.candidate_output)
        candidate.update(evidence)
        return BackendOutput(
            candidate_output=candidate,
            confidence=output.confidence,
            uncertainty=output.uncertainty,
            cost=output.cost,
            trace=output.trace,
        )

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]:
        return {"status": "disabled", "relations": []}

    @staticmethod
    def _graph(
        identity: SymbiosisIdentity, inputs: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        attestation = dict(inputs.get("causal_attestation") or {})
        observation = inputs.get("observation") or {}
        metadata = inputs.get("scenario_metadata") or {}
        variable = str(metadata.get("main_variable") or "").strip()
        attested_variable = str(attestation.get("main_variable") or "").strip()
        comparable = bool(variable and attested_variable == variable)
        base = _number(observation.get(variable)) if variable else None
        factual = _number(attestation.get("factual_delta"))
        counter = _number(attestation.get("counterfactual_delta"))
        factual_value = _number(attestation.get("factual_value"))
        counter_value = _number(attestation.get("counterfactual_value"))
        if factual is None and factual_value is not None and base is not None:
            factual = factual_value - base
        if counter is None and counter_value is not None and base is not None:
            counter = counter_value - base
        effect = factual - counter if comparable and factual is not None and counter is not None else None
        confidence = min(1.0, abs(effect) * 5.0) if effect is not None else 0.0
        provenance = f"causal_attestation:{identity.episode_id}"
        nodes = []
        edges = []
        episodic_edge_id = None
        if effect is not None:
            nodes = [
                {"id": "intervention", "node_type": "intervention", "feature_vector": [1.0, effect, factual, counter], "provenance": provenance, "scenario_id": identity.scenario_id, "schema_version": GRAPH_SCHEMA_VERSION},
                {"id": variable, "node_type": "world_variable", "feature_vector": [1.0, effect, abs(effect), confidence], "provenance": provenance, "scenario_id": identity.scenario_id, "schema_version": GRAPH_SCHEMA_VERSION},
            ]
            if effect != 0.0:
                episodic_edge_id = f"episodic-effect:{variable}"
                signed = max(-1.0, min(1.0, effect))
                edges.append(
                    {"id": episodic_edge_id, "source": "intervention", "target": variable, "edge_type": "causal_negative" if signed < 0.0 else "causal_positive", "signed_strength": signed, "confidence": confidence, "provenance": provenance, "canonical": False, "schema_version": GRAPH_SCHEMA_VERSION}
                )
                canonical = _canonical_intervention_edge(metadata, attestation)
                if canonical is not None:
                    edges.append(
                        {"id": f"canonical-effect:{variable}", "source": "intervention", "target": variable, "edge_type": "causal_negative" if canonical["signed_strength"] < 0.0 else "causal_positive", "signed_strength": canonical["signed_strength"], "confidence": 0.0, "provenance": canonical["provenance"], "canonical": True, "schema_version": GRAPH_SCHEMA_VERSION}
                    )
        if not nodes:
            nodes = [
                {"id": "insufficient-evidence", "node_type": "evidence", "feature_vector": [0.0, 0.0, 0.0, 0.0], "provenance": provenance, "scenario_id": identity.scenario_id, "schema_version": GRAPH_SCHEMA_VERSION}
            ]
        optimization = str(attestation.get("optimization_direction") or "")
        goal_alignment = _goal_alignment(effect, optimization)
        graph = {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "scenario_id": identity.scenario_id,
            "nodes": nodes,
            "edges": edges,
        }
        evidence = {
            "causal_effect": {
                "variable": variable or None,
                "factual_delta": factual,
                "counterfactual_delta": counter,
                "signed_effect": effect,
                "measurement_status": "measured" if effect is not None else "unmeasured",
                "zero_effect": effect == 0.0 if effect is not None else None,
                "episodic_edge_id": episodic_edge_id,
            },
            "goal_alignment": goal_alignment,
            "evidence_status": (
                "measured_zero_effect"
                if effect == 0.0
                else "measured"
                if effect is not None
                else "insufficient_evidence"
            ),
        }
        return graph, evidence

    @staticmethod
    def compare(candidate: Any, state: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(candidate, Mapping) or not candidate.get("relations"):
            return {"verdict": "disabled_or_no_candidate", "agreement": None}
        alignment = candidate.get("goal_alignment") or {}
        n4_relation = alignment.get("status")
        cau, ctf = state.get("cau_link") or {}, state.get("ctf_checked") or {}
        canonical_support = bool(cau.get("helps_goal")) and ctf.get("supports_choice") is not False
        canonical_relation = "helps_goal" if canonical_support else "harms_goal"
        agreement = n4_relation == canonical_relation if n4_relation in {"helps_goal", "harms_goal"} else None
        return {
            "verdict": "agreement" if agreement is True else "disagreement" if agreement is False else "unavailable",
            "agreement": agreement,
            "n4_relation": n4_relation,
            "canonical_relation": canonical_relation,
            "causal_effect": candidate.get("causal_effect"),
            "backend_disagreement": candidate["relations"][0].get("canonical_disagreement"),
            "authorities": ["CAU", "CTF", "C-GWM"],
            "decision_influence": "none",
        }


class N5Adapter:
    organ = "N5"
    capability = "deterministic_ingestion"
    authority_ceiling = NeuralMode.PROVISIONAL
    consumer = "SMG+MFM"
    reference_id = "rnfe:N5:deterministic_ingestion:chunker-v1"
    # Cableada, por la misma razón que N3: techo PROVISIONAL con la puerta
    # escrita (`n5_ingest.py:280`) y desconectada. Valida el esquema H-Net y la
    # identidad del texto ingerido antes de dejar pasar nada.
    admission_gate = HNetBoundaryAdmission()

    def __init__(self) -> None:
        self.chunker = DeterministicChunker(max_bytes=256)

    def infer(self, request: NeuralInferenceRequest, context: Mapping[str, Any]) -> BackendOutput:
        inputs = context["inputs"]
        memory_text = " ".join(
            canonical_json_bytes(item.get("structure", {})).decode("utf-8")[:512]
            for item in inputs.get("memory_hits", [])[:3]
        )
        content = "\n".join(
            part for part in (str(inputs.get("proposition") or ""), str(inputs.get("formula") or ""), memory_text) if part
        )[:2048]
        chunks = [chunk.to_dict() for chunk in self.chunker.chunk(content)]
        return BackendOutput(
            candidate_output={
                "status": "ok", "backend": "deterministic_chunker", "hnet_active": False,
                "fallback_declared": "hnet_artifact_unavailable", "chunks": chunks,
                "memory_candidates": [{"chunk": chunk, "provenance": "scenario_observation+formula+authorized_memory", "promotion": "requires_existing_mfm_gate"} for chunk in chunks],
            },
            confidence=1.0, uncertainty=0.0,
            cost={"chunks": len(chunks), "ram_mb": 0.25, "vram_mb": 0.0},
        )

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]:
        return {"chunks": [], "memory_candidates": [], "fallback": "disabled"}


class N6Adapter:
    organ = "N6"
    capability = "structural_evolution_proposal"
    authority_ceiling = NeuralMode.SHADOW
    consumer = "sandbox+certification+autoevolution"
    reference_id = "rnfe:N6:structural_evolution_proposal:bounded-reference-v1"
    admission_gate = None

    def infer(self, request: NeuralInferenceRequest, context: Mapping[str, Any]) -> BackendOutput:
        identity: SymbiosisIdentity = context["identity"]
        viability = context.get("viability") or {}
        reasoning = context.get("reasoning") or {}
        margin = float(viability.get("viability_margin", 0.0) or 0.0)
        trace = reasoning.get("trace") or []
        cost = sum(float((item.get("detail") or {}).get("cost", 0.0) or 0.0) for item in trace)
        proposal = None
        if margin < 0.75 or cost > 5.0:
            proposal = {
                "schema_version": "n6-structural-proposal-v1",
                "proposal_id": f"n6-{identity.episode_id}",
                "mutation_type": "optional_family_budget", "target": "reasoning_optional_budget",
                "value": "decrease_one", "expected_gain": round(max(0.01, (0.75 - margin) * 0.2), 6),
                "rollback_token": f"shadow-{identity.trace_group_id}", "lineage_id": identity.lineage_id,
            }
        sandbox = {
            "evaluated": proposal is not None,
            "safe": proposal is not None and proposal["mutation_type"] == "optional_family_budget",
            "applied": False,
            "reason": "shadow_no_mutation" if proposal is not None else "no_degradation_trigger",
        }
        return BackendOutput(
            candidate_output={
                "status": "proposed" if proposal is not None else "abstained",
                "proposal": proposal, "sandbox": sandbox,
                "sandbox_verdict": "shadow_safe_not_applied" if sandbox["safe"] else "abstained",
                "applied": False, "consumers": ["sandbox", "certification", "autoevolution_evidence"],
            },
            confidence=0.5 if proposal is not None else 1.0,
            uncertainty=0.5 if proposal is not None else 0.0,
            cost={"evaluations": 1, "ram_mb": 0.05, "vram_mb": 0.0},
        )

    def fallback(self, identity: SymbiosisIdentity) -> Mapping[str, Any]:
        return {"status": "disabled", "proposal": None, "applied": False}


def canonical_adapter_registry() -> dict[str, CanonicalOrganAdapter]:
    adapters: list[CanonicalOrganAdapter] = [
        N1Adapter(), N2Adapter(), N3Adapter(), N4Adapter(), N5Adapter(), N6Adapter()
    ]
    registry = {adapter.organ: adapter for adapter in adapters}
    expected = {f"N{index}" for index in range(1, 7)}
    if len(registry) != len(adapters) or set(registry) != expected:
        raise RuntimeError("canonical_neural_adapter_registry_incomplete_or_duplicated")
    return registry


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_intervention_edge(
    metadata: Mapping[str, Any], attestation: Mapping[str, Any]
) -> dict[str, Any] | None:
    signature = metadata.get("causal_signature")
    if not isinstance(signature, Mapping):
        return None
    intervention = str(attestation.get("intervention") or "")
    variable = str(metadata.get("main_variable") or "")
    for effect in signature.get("intervention_effects") or ():
        if not isinstance(effect, Mapping):
            continue
        if str(effect.get("intervention_name") or "") != intervention:
            continue
        if str(effect.get("target_variable") or "") != variable:
            continue
        magnitude = _number(effect.get("expected_magnitude"))
        direction = str(effect.get("expected_direction") or "")
        if magnitude is None or magnitude <= 0.0 or direction not in {"+", "-"}:
            return None
        return {
            "signed_strength": min(1.0, magnitude) * (1.0 if direction == "+" else -1.0),
            "provenance": (
                f"scenario.causal_signature:{signature.get('scenario_name')}"
                f"@{signature.get('scenario_version')}"
            ),
        }
    return None


def _goal_alignment(effect: float | None, optimization: str) -> dict[str, Any]:
    if effect is None:
        return {"status": "unavailable", "measurement_status": "unmeasured", "reason": "causal_effect_unmeasured"}
    if effect == 0.0:
        return {"status": "neutral", "measurement_status": "measured", "reason": "zero_physical_effect"}
    if optimization == "minimize":
        status = "helps_goal" if effect < 0.0 else "harms_goal"
    elif optimization == "maximize":
        status = "helps_goal" if effect > 0.0 else "harms_goal"
    else:
        return {"status": "unavailable", "measurement_status": "unmeasured", "reason": "target_band_requires_explicit_bounds"}
    return {"status": status, "measurement_status": "measured", "reason": f"optimization_direction:{optimization}"}
