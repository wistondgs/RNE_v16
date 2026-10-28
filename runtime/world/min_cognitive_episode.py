"""Episodio cognitivo mínimo: observación -> signo -> LOTF -> intervención -> actualización."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Dict
from uuid import uuid4

from runtime.certification.promotion_gate import PromotionGate
from runtime.certification.transfer_assessment import retrieval_metrics_from_hits
from runtime.lotf import LOTFMin
from runtime.memory.mfm_lite.retrieval import MemoryRetrieval
from runtime.reality.belief_state import BeliefState, build_belief_state, compute_belief_shift
from runtime.reasoning.context import build_reasoning_context, resolve_reasoning_mode
from runtime.reasoning.scheduler_meta.meta_scheduler import MetaScheduler
from runtime.smg import SMGMin
from runtime.storage import get_storage
from runtime.symbolic.eml import EMLRunner
from runtime.storage.records import utc_now_iso
from runtime.world.causal_attestation import build_causal_attestation
from runtime.world.cgwm_min import CGWMMin
from runtime.world.registry import get_scenario


class MinimalCognitiveEpisodeRunner:
    def __init__(
        self,
        *,
        storage=None,
        run_id: str | None = None,
        closure_profile: str = "baseline_fixed",
    ):
        self.storage = storage or get_storage()
        self.run_id = run_id or f"run-{uuid4()}"
        valid_closure_profiles = {"baseline_fixed", "adaptive_min"}
        if closure_profile not in valid_closure_profiles:
            raise ValueError(
                f"closure_profile inválido: '{closure_profile}'. "
                f"Válidos: {sorted(valid_closure_profiles)}"
            )
        self.closure_profile = closure_profile
        self.reasoning_mode = resolve_reasoning_mode(closure_profile)
        self.smg = SMGMin(storage=self.storage, run_id=self.run_id)
        self.lotf = LOTFMin()
        self.world = CGWMMin()
        self.scheduler = MetaScheduler(trace_store=self.storage, mode=self.reasoning_mode)
        self.memory_retrieval = MemoryRetrieval(storage=self.storage)
        self.promotion_gate = PromotionGate(storage=self.storage)
        self.eml_mode = os.environ.get("RNFE_EML_MODE", "disabled").strip().lower()
        self.eml_runner = EMLRunner(storage=self.storage)
        # P9.6 — este runner ni siquiera construía belief_state: certificaba a ciegas.
        self._previous_belief: BeliefState | None = None

    def _build_eml_dataset(
        self,
        *,
        observation: Dict[str, Any],
        factual: Dict[str, Any],
        counterfactual: Dict[str, Any],
    ) -> list[dict[str, float]]:
        x = float(observation.get("temperature", 0.0))
        cf = float(counterfactual.get("temperature", x))
        y = float(factual.get("temperature", x))
        return [
            {"x": x, "cf": cf, "y": y},
            {"x": max(0.0, x - 0.02), "cf": cf, "y": y},
            {"x": min(1.0, x + 0.02), "cf": cf, "y": y},
        ]

    def run_episode(self, *, external_heat: float = 0.04) -> Dict[str, Any]:
        episode_id = f"episode-{uuid4()}"
        observation = self.world.observe()
        observation_ref = self.smg.add_observation(observation)

        temp_high = observation["temperature"] >= self.world.alarm_threshold
        proposition = "TEMP_HIGH" if temp_high else "TEMP_NORMAL"
        sign_main = self.smg.create_sign(
            proposition=proposition,
            observation_id=observation_ref.observation_id,
            metadata={"temperature": observation["temperature"]},
        )

        formula = "TEMP_HIGH -> ACTIVATE_COOLING"
        ast = self.lotf.parse(formula)
        self.lotf.check(ast, {"TEMP_HIGH": "bool", "ACTIVATE_COOLING": "bool"})

        memory_hits = self.memory_retrieval.retrieve(
            run_id=self.run_id,
            query={
                "proposition": proposition,
                "alarm": observation.get("alarm"),
            },
            limit=3,
        )
        intervention = "activate_cooling" if temp_high else "deactivate_cooling"
        if memory_hits:
            top = memory_hits[0].get("structure", {})
            if (
                top.get("relation_kind") == "support"
                and temp_high
                and top.get("temperature") is not None
            ):
                intervention = "activate_cooling"

        counterfactual = self.world.simulate_counterfactual(
            intervention="deactivate_cooling", external_heat=external_heat
        )
        factual = self.world.factual_transition(
            intervention=intervention, external_heat=external_heat
        )

        sign_intervention = self.smg.create_sign(
            proposition="ACTIVATE_COOLING" if intervention == "activate_cooling" else "KEEP_IDLE",
            observation_id=observation_ref.observation_id,
            metadata={"intervention": intervention},
        )
        relation_kind = (
            "support"
            if factual["temperature"] <= counterfactual["temperature"]
            else "contradiction"
        )
        try:
            signature = get_scenario("thermal_homeostasis").causal_signature
        except Exception:
            signature = None
        causal_attestation = build_causal_attestation(
            scenario_name="thermal_homeostasis",
            main_variable="temperature",
            intervention=intervention,
            observation=observation,
            factual=factual,
            counterfactual=counterfactual,
            relation_kind=relation_kind,
            signature=signature,
        )
        relation = self.smg.link_signs(
            source_sign_id=sign_main.sign_id,
            target_sign_id=sign_intervention.sign_id,
            kind=relation_kind,
            metadata={
                "factual_temperature": factual["temperature"],
                "counterfactual_temperature": counterfactual["temperature"],
            },
        )

        reasoning_context = build_reasoning_context(
            episode_id=episode_id,
            run_id=self.run_id,
            observation=observation,
            intervention=intervention,
            formula=formula,
            memory_hits=memory_hits,
            counterfactual=counterfactual,
            updated_world=factual,
            relation_kind=relation_kind,
            scenario="thermal_homeostasis",
            closure_profile=self.closure_profile,
            reasoning_mode=self.reasoning_mode,
            extra_signals={"causal_attestation": causal_attestation},
        )
        reasoning = self.scheduler.run(reasoning_context)
        episode_payload = {
            "episode_id": episode_id,
            "timestamp": utc_now_iso(),
            "closure_profile": self.closure_profile,
            "context": {
                "observation": observation,
                "formula": formula,
                "intervention": intervention,
                "counterfactual": counterfactual,
                "retrieved_memory": memory_hits,
                "memory_rag_attestation": reasoning_context.get("memory_rag_attestation"),
                "causal_attestation": causal_attestation,
                "closure_profile": self.closure_profile,
            },
            "result": {
                "updated_world": factual,
                "relation_kind": relation_kind,
                "reasoning_sequence": reasoning["sequence"],
            },
            "trace": reasoning["trace"],
        }
        self.storage.append_event(
            event_type="episode.closed",
            payload=episode_payload,
            run_id=self.run_id,
            source="min_cognitive_episode",
        )

        artifact_blob = json.dumps(
            {
                "episode": episode_payload,
                "smg_snapshot": self.smg.snapshot(),
                "relation": asdict(relation),
            },
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        )
        artifact = self.storage.materialize_artifact(
            run_id=self.run_id,
            kind="episode_report",
            content=artifact_blob,
            filename=f"{episode_id}.json",
            metadata={"episode_id": episode_id},
        )
        episode_result = {
            "episode": episode_payload,
            "smg_snapshot": self.smg.snapshot(),
            "reasoning": reasoning,
            "artifact": asdict(artifact),
            "run_id": self.run_id,
        }
        # P9.6 (paso 1) — MEDIR, NO FABRICAR. Este runner certificaba sin belief_state
        # siquiera: `assess_transfer` no encontraba `episode_result["belief_state"]` y caía
        # en los rellenos favorables (policy=0.5, causal=0.5, kl=0.0). Ahora el episodio
        # construye su creencia y, cuando hay episodio previo, mide el SHIFT contra él.
        #
        # Lo que NO se puede obtener honestamente acá y por lo tanto NO se inventa:
        #   - `transition_vector`: exige el episodio anterior COMPLETO y un
        #     `CompatibilityAssessment`; este runner mínimo no conserva el anterior ni tiene
        #     perfil estructural cargado. Queda ausente ⇒ la pureza la mide `assess_transfer`
        #     con las métricas de retrieval del propio episodio (paso 5).
        #   - `reality_assessment`: nadie lo construye en este camino.
        current_belief = build_belief_state(episode_result=episode_result)
        belief_prior = self._previous_belief
        episode_result["belief_state"] = {
            "prior": asdict(belief_prior) if belief_prior else None,
            "posterior": asdict(current_belief),
        }
        self._previous_belief = current_belief
        belief_shift = (
            compute_belief_shift(prior=belief_prior, posterior=current_belief)
            if belief_prior is not None
            else None  # primer episodio: no hay prior. Ausencia, no un cero favorable.
        )

        certification = self.promotion_gate.process_episode(
            run_id=self.run_id,
            episode_result=episode_result,
            belief_shift=belief_shift,
            retrieval_metrics=retrieval_metrics_from_hits(memory_hits),
        )
        eml_shadow = {"enabled": False, "status": "disabled"}
        if self.eml_mode == "shadow":
            dataset = self._build_eml_dataset(
                observation=observation,
                factual=factual,
                counterfactual=counterfactual,
            )
            eml_out = self.eml_runner.run_shadow(
                run_id=self.run_id,
                episode_id=episode_id,
                rows=dataset,
            )
            top = eml_out["run"]["top_candidates"]
            eml_shadow = {
                "enabled": True,
                "status": "ok",
                "eml_run_id": eml_out["run"]["eml_run_id"],
                "candidate_count": eml_out["run"]["candidate_count"],
                "top_composite": top[0]["composite_score"] if top else 0.0,
                "top_expr_signature": str(top[0]["expr"]) if top else "",
                "artifacts": eml_out["artifacts"],
            }
            episode_result["episode"]["context"]["eml_shadow"] = {
                "eml_run_id": eml_shadow["eml_run_id"],
                "candidate_count": eml_shadow["candidate_count"],
                "top_composite": eml_shadow["top_composite"],
                "top_expr_signature": eml_shadow["top_expr_signature"],
            }
        return {
            **episode_result,
            "certification": {
                "certificate_id": certification["certificate"].certificate_id,
                "verdict": certification["certificate"].verdict,
                "promotion_candidate": certification["certificate"].promotion_candidate,
                "decision_verdict": certification["decision"].verdict,
            },
            "eml_shadow": eml_shadow,
        }
