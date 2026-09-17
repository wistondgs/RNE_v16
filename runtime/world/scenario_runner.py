"""Runner de episodio cognitivo genérico que soporta múltiples escenarios."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from typing import Any, Dict, Mapping
from uuid import uuid4

from runtime.certification.promotion_gate import PromotionGate
from runtime.certification.transfer_assessment import retrieval_metrics_from_hits
from runtime.lotf import LOTFMin
from runtime.memory.mfm_lite.retrieval import MemoryRetrieval
from runtime.neural import NeuralRuntimeConfig
from runtime.neural.integration import (
    ConsumerVerdictClass,
    SymbiosisIdentity,
    SymbioticNeuralCoordinator,
)
from runtime.organism.autoevolution import AutoEvolutionController
from runtime.organism.adaptive_state import AdaptationPlanner, AdaptiveStateStore
from runtime.organism.constitution import OrganismConstitution
from runtime.organism.dynamic_state import OrganismDynamicState, canonical_hash, measured
from runtime.organism.identity import mint_lineage_id, mint_organism_id
from runtime.organism.lineage import LineageState
from runtime.organism.life_transition import DynamicLifeChain
from runtime.organism.regime_model import (
    REGIME_REGISTRY,
    compare_regimes,
    get_regime_for_scenario,
)
from runtime.organism.state import OrganismState, IdentityState, transition_organism_state
from runtime.organism.trajectory import OrganismTrajectory
from runtime.organism.trajectory_replay import ShadowTrajectoryReplay
from runtime.organism.trajectory_window import TrajectoryWindowBuilder
from runtime.organism.viability import ViabilityKernel
from runtime.reasoning.context import build_reasoning_context, resolve_reasoning_mode
from runtime.reasoning.scheduler_meta.meta_scheduler import MetaScheduler
from runtime.reality.belief_state import BeliefState, build_belief_state, compute_belief_shift
from runtime.world.compatibility import ScenarioCompatibilityGraph
from runtime.smg import SMGMin
from runtime.storage import get_storage
from runtime.storage.records import utc_now_iso
from runtime.reasoning.families import a12 as a12_family
from runtime.world.intervention_override import (
    OverrideDecision,
    evaluate_foresight_override,
    evaluate_override,
    is_actuation_enabled,
    outcome_effectiveness,
)
from runtime.world.causal_attestation import build_causal_attestation
from runtime.symbolic.eml import EMLRunner

from .scenario import CognitiveScenario, ScenarioObservation
from .registry import get_scenario, DEFAULT_SCENARIO


def _external_reasoner_runtime_flag() -> bool:
    """True si RNFE_EXTERNAL_REASONER_RUNTIME habilita el razonador externo vivo."""
    return os.environ.get("RNFE_EXTERNAL_REASONER_RUNTIME", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class ScenarioEpisodeRunner:
    """Runner de episodio cognitivo que opera sobre escenarios parametrizables.

    Este runner es la versión generalizada de MinimalCognitiveEpisodeRunner
    que puede operar sobre cualquier escenario que implemente CognitiveScenario.
    """

    def __init__(
        self,
        *,
        storage=None,
        run_id: str | None = None,
        scenario: CognitiveScenario | str | None = None,
        scenario_kwargs: Dict[str, Any] | None = None,
        memory_filter_mode: str = "strict_same_scenario",
        closure_profile: str = "baseline_fixed",
        organism_state: OrganismState | None = None,
        lineage: LineageState | None = None,
        reward_guided=None,
        retention_signal: str = "ioc",
        trajectory_reward: str = "none",
    ):
        """Inicializa runner con escenario especificado.

        Args:
            storage: Storage facade opcional.
            run_id: ID de corrida.
            scenario: Escenario como instancia, nombre string, o None para default.
            scenario_kwargs: Kwargs para crear escenario si es string.
            memory_filter_mode: Modo de filtrado de memoria por escenario
                ('strict_same_scenario' o 'cross_scenario_analogical').
                El alias 'analogical' se normaliza automáticamente.
            closure_profile: Perfil de cierre a usar ('baseline_fixed' o 'adaptive_min').
            organism_state: Estado inicial del organismo (para continuar una vida
                a través de varios runners/regímenes, p. ej. el life-loop).
            lineage: LineageState compartido para continuidad generacional.
            retention_signal: qué cantidad decide si una automodificación se
                conserva o se revierte ('ioc' | 'viability' | 'both'). Ver
                RETENTION_SIGNALS en runtime/organism/autoevolution.py.
            trajectory_reward: de dónde saca el trayecto del organismo su señal
                de éxito ('none' | 'previous_certificate'). Ver el bloque 12c.
        """
        if trajectory_reward not in ("none", "previous_certificate"):
            raise ValueError(
                f"TRAJECTORY_REWARD_UNKNOWN: {trajectory_reward!r}; "
                "conocidas: ['none', 'previous_certificate']"
            )
        self._trajectory_reward = trajectory_reward
        self._last_certification: Dict[str, Any] | None = None
        self.storage = storage or get_storage()
        self.run_id = run_id or f"run-{uuid4()}"
        self._trajectory_regime_label = DEFAULT_SCENARIO

        # Resolver escenario
        if scenario is None:
            self.scenario = get_scenario(DEFAULT_SCENARIO, **(scenario_kwargs or {}))
            self._trajectory_regime_label = DEFAULT_SCENARIO
        elif isinstance(scenario, str):
            self.scenario = get_scenario(scenario, **(scenario_kwargs or {}))
            self._trajectory_regime_label = scenario
        else:
            self.scenario = scenario
            self._trajectory_regime_label = self.scenario.config.name

        # Normalize memory filter mode alias
        if memory_filter_mode == "analogical":
            memory_filter_mode = "cross_scenario_analogical"
        _VALID_MEMORY_MODES = {"strict_same_scenario", "cross_scenario_analogical"}
        if memory_filter_mode not in _VALID_MEMORY_MODES:
            raise ValueError(
                f"memory_filter_mode inválido: '{memory_filter_mode}'. "
                f"Válidos: {sorted(_VALID_MEMORY_MODES)}"
            )
        self.memory_filter_mode = memory_filter_mode

        _VALID_CLOSURE_PROFILES = {"baseline_fixed", "adaptive_min"}
        if closure_profile not in _VALID_CLOSURE_PROFILES:
            raise ValueError(
                f"closure_profile inválido: '{closure_profile}'. "
                f"Válidos: {sorted(_VALID_CLOSURE_PROFILES)}"
            )
        self.closure_profile = closure_profile
        self.reasoning_mode = resolve_reasoning_mode(closure_profile)
        # Señales de recursos (host+GPU) inyectadas por el LifeKernel por ciclo.
        # Vacío por defecto -> el contexto de razonamiento no cambia (byte-idéntico).
        self._resource_signals: Dict[str, Any] = {}
        # Habilitación por-episodio del razonador externo (tier_3). El runtime
        # solo lo agenda si además el perfil admitido y el gate lo permiten (Bloque C).
        self._external_reasoner_enabled: bool = False
        # B41: sobre CausalContext del step (aditivo, gated por el kernel). None ⇒ no-op.
        self._causal_context: Dict[str, Any] | None = None
        # Experiencia: el organismo recuerda sus golpes y aprende (RNFE_EXPERIENCE).
        # B41: el namespace es organism_id (cross-vida). El runner NO acuña con convención
        # propia (nada de org-{run_id}): usa la función de acuñación compartida (SSOT). En
        # el life-loop, el kernel soberano lo REEMPLAZA vía set_organism_id con el genoma real.
        from runtime.organism.experience import ExperienceStore, experience_enabled

        self._organism_id: str = mint_organism_id()
        # Linaje standalone (solo si no llega uno del kernel): un único lineage_id
        # compartido entre el estado de génesis y el LineageState, vía la SSOT.
        _standalone_lineage_id = mint_lineage_id()
        self._experience = ExperienceStore(storage=self.storage) if experience_enabled() else None
        self._experience_lessons: List[Dict[str, Any]] = []

        self.smg = SMGMin(storage=self.storage, run_id=self.run_id)
        self.lotf = LOTFMin()
        self.scheduler = MetaScheduler(trace_store=self.storage, mode=self.reasoning_mode)
        self.memory_retrieval = MemoryRetrieval(storage=self.storage)
        self.promotion_gate = PromotionGate(storage=self.storage)
        self.eml_mode = os.environ.get("RNFE_EML_MODE", "disabled").strip().lower()
        self.eml_runner = EMLRunner(storage=self.storage)
        self._previous_belief: BeliefState | None = None
        # P9.6 — el episodio anterior COMPLETO: sin él no hay transición que medir y
        # `compute_transition_vector` (que ya existía) no se podía llamar. Es el insumo
        # del que sale la pureza de memoria REAL que antes se fabricaba en `1.0`.
        self._previous_result: Dict[str, Any] | None = None
        # Compatibilidad del escenario CONSIGO MISMO: el runner vive en un escenario fijo
        # (el kernel lo reconstruye al cambiar de escenario), así que toda transición que
        # este runner puede observar es intra-escenario. Se COMPUTA (no se asume): si el
        # perfil no fuera auto-equivalente, se vería.
        self._intra_compatibility: Any | None = None

        # T5 SOVEREIGNTY: Initialize organism trajectory as primary runtime unit
        self._organism_state = organism_state or OrganismState(
            state_id=f"state-0-{self._organism_id}",
            timestamp=utc_now_iso(),
            active_regime="unknown",
            episode_count=0,
            identity=IdentityState(
                lineage_id=_standalone_lineage_id,
                constitution_hash="",
            ),
        )
        self._organism_trajectory = OrganismTrajectory(
            organism_id=self._organism_id,
            start_timestamp=utc_now_iso(),
        )
        self._constitution = OrganismConstitution()
        self._viability_kernel = ViabilityKernel(constitution=self._constitution)

        # R2 — vida: linaje activo (μₜ) + lazo de autoevolución (ρₜ).
        # Los mandos (knobs) son parámetros de comportamiento REALES del runner;
        # el controlador solo actúa bajo degradación sostenida, así que los
        # baselines sanos quedan numéricamente intactos.
        self.memory_retrieval_limit = 3
        if lineage is not None:
            self._lineage = lineage
        else:
            self._lineage = LineageState(lineage_id=_standalone_lineage_id)
            self._lineage.record_genesis(self._constitution, timestamp=utc_now_iso())
        self._autoevolution = AutoEvolutionController(
            run_id=self.run_id,
            storage=self.storage,
            lineage=self._lineage,
            knob_reader=lambda: {
                "memory_retrieval_limit": self.memory_retrieval_limit,
                "memory_filter_mode": self.memory_filter_mode,
            },
            knob_writer=self._apply_knob_changes,
            retention_signal=retention_signal,
        )

        # Multiplicación de ganancia (canon §8): selector de overlays guiado por
        # la recompensa semi-Markov. Apagado por defecto (disciplina sombra);
        # se activa con RNFE_REWARD_GUIDED_SELECTION=1.
        from runtime.reasoning.scheduler_meta.reward_guided import (
            RewardGuidedOverlaySelector,
            is_reward_guided_enabled,
        )

        self._reward_guided: RewardGuidedOverlaySelector | None = (
            reward_guided
            if reward_guided is not None
            else (
                RewardGuidedOverlaySelector(storage=self.storage)
                if is_reward_guided_enabled()
                else None
            )
        )
        # Reglas inducidas transferidas por una ecología multi-organismo
        # (modo reasoning_policy_plus_rules). None en el camino de un solo organismo.
        self._inherited_rules: list | None = None
        # Única frontera neuronal viva. Construirla no carga modelos; N0 OFF no
        # ejecuta productores ni adquiere artefactos.
        self._neural = SymbioticNeuralCoordinator(
            storage=self.storage,
            config=NeuralRuntimeConfig.from_env(),
        )
        self._dynamic_chain = DynamicLifeChain(
            organism_id=self._organism_id,
            lineage_id=self._lineage.lineage_id,
            run_id=self.run_id,
        )
        self._adaptive_states = AdaptiveStateStore(
            organism_id=self._organism_id,
            lineage_id=self._lineage.lineage_id,
        )
        self._adaptation_planner = AdaptationPlanner()

    def _maybe_override_intervention(
        self,
        *,
        reasoning_state: Dict[str, Any],
        greedy_intervention: str,
        factual: Any,
        external_input: float,
    ) -> "tuple[OverrideDecision, Any]":
        """Decide el override determinista guardado (sombra: OFF salvo flag).

        Devuelve (decision, candidate_transition). La transición candidata se
        simula fresca (el contrafactual naive del runner no es la alterna real).
        """
        if not is_actuation_enabled():
            return OverrideDecision(fired=False, guard_reason="actuation_disabled"), None
        mv = self.scenario.config.main_variable
        try:
            direction = str(self.scenario.causal_signature.optimization_direction)
        except Exception:
            direction = "minimize"
        allowed = list(self.scenario.config.interventions)

        # 1) Override de PREVISIÓN (A11+A12): guard de horizonte, corre primero. A12
        # ya integró toda la evidencia (no-monotonía + Bayes-factor + ACT) y A11
        # certificó el breach diferido del greedy; el guard de un paso lo vetaría.
        #
        # El decisor A12 debe usar la traza COMPLETA. El scheduler puede ejecutarlo
        # antes que otras familias; para la ACTUACIÓN lo recomputamos sobre el estado
        # final (ya con todas las claves: imagination_*/ctf/cau/ded/prob). Gated
        # internamente por RNFE_A12_DEEP (idle ⇒ sin claves ⇒ no dispara).
        a12_delta = a12_family.execute(reasoning_state).get("state_delta", {})
        foresight_state = {**reasoning_state, **a12_delta} if a12_delta else reasoning_state
        foresight = evaluate_foresight_override(
            reasoning_state=foresight_state,
            allowed_interventions=allowed,
            greedy_intervention=greedy_intervention,
        )
        if foresight.fired:
            candidate = self.scenario.simulate_counterfactual(
                intervention=foresight.to_intervention, external_input=external_input
            )
            return foresight, candidate

        # 2) Override greedy guardado de UN paso (existente): conflicto estructural +
        # familia deliberativa (opt/plan/ind) + mejora inmediata certificada.
        sim_cache: Dict[str, Any] = {}

        def simulate_value(intervention: str) -> float:
            transition = self.scenario.simulate_counterfactual(
                intervention=intervention, external_input=external_input
            )
            sim_cache[intervention] = transition
            return float(transition.state.get(mv, 0.0))

        decision = evaluate_override(
            reasoning_state=reasoning_state,
            allowed_interventions=list(self.scenario.config.interventions),
            greedy_intervention=greedy_intervention,
            direction=direction,
            factual_value=float(factual.state.get(mv, 0.0)),
            simulate_value=simulate_value,
        )
        candidate = sim_cache.get(decision.to_intervention) if decision.fired else None
        return decision, candidate

    def _apply_knob_changes(self, changes: Dict[str, Any]) -> None:
        """Aplica una modificación aceptada sobre los mandos reales del runner."""
        if "memory_retrieval_limit" in changes:
            self.memory_retrieval_limit = max(1, int(changes["memory_retrieval_limit"]))
        if "memory_filter_mode" in changes:
            mode = str(changes["memory_filter_mode"])
            if mode in {"strict_same_scenario", "cross_scenario_analogical"}:
                self.memory_filter_mode = mode

    @property
    def organism_state(self) -> OrganismState:
        """Estado vivo del organismo (para continuarlo en otro runner/régimen)."""
        return self._organism_state

    @property
    def lineage(self) -> LineageState:
        """Linaje del organismo (continuidad generacional)."""
        return self._lineage

    def _build_scenario_metadata(self) -> Dict[str, Any]:
        """Construye metadata formal del escenario activo.

        Returns:
            Dict con identidad completa del escenario: nombre, versión,
            hash de configuración, variable principal, umbral e intervenciones.
        """
        cfg = self.scenario.config
        config_blob = json.dumps(
            {
                "name": cfg.name,
                "main_variable": cfg.main_variable,
                "alarm_threshold": cfg.alarm_threshold,
                "interventions": cfg.interventions,
                "formula_template": cfg.formula_template,
                "type_context": cfg.type_context,
            },
            sort_keys=True,
        )
        config_hash = hashlib.sha256(config_blob.encode()).hexdigest()[:12]
        signature = self.scenario.causal_signature
        return {
            "scenario_name": cfg.name,
            "scenario_version": "1.0",
            "scenario_config_hash": config_hash,
            "main_variable": cfg.main_variable,
            "alarm_threshold": cfg.alarm_threshold,
            "interventions": cfg.interventions,
            "causal_signature": {
                "scenario_name": signature.scenario_name,
                "scenario_version": signature.scenario_version,
                "main_variable": signature.main_variable,
                "optimization_direction": signature.optimization_direction,
                "intervention_effects": [
                    {
                        "intervention_name": effect.intervention_name,
                        "target_variable": effect.target_variable,
                        "expected_direction": effect.expected_direction,
                        "expected_magnitude": effect.expected_magnitude,
                    }
                    for effect in signature.intervention_effects
                ],
            },
        }

    def _self_compatibility(self):
        """Compatibilidad del escenario CONSIGO MISMO (la transición que este runner ve).

        P9.6: `compute_transition_vector` exige un `CompatibilityAssessment`. El runner vive
        en un escenario fijo — el kernel lo reconstruye al cambiar de escenario
        (`kernel._runner_key`) —, así que toda transición episodio→episodio que puede
        observar es INTRA-escenario. La compatibilidad correspondiente no se asume: se
        COMPUTA con el grafo real sobre el perfil estructural del escenario (da
        `equivalent`/1.0 porque el escenario es idéntico a sí mismo, no porque lo
        hayamos escrito a mano). Se cachea: el perfil no cambia durante la vida del runner.
        """
        if self._intra_compatibility is None:
            self._intra_compatibility = ScenarioCompatibilityGraph().assess(
                self.scenario.structural_profile,
                self.scenario.structural_profile,
            )
        return self._intra_compatibility

    def _build_eml_dataset(
        self,
        *,
        observation: Dict[str, Any],
        factual: Dict[str, Any],
        counterfactual: Dict[str, Any],
    ) -> list[dict[str, float]]:
        """Construye dataset EML a partir del escenario."""
        main_var = self.scenario.config.main_variable
        x = float(observation.get(main_var, 0.0))
        cf = float(counterfactual.get(main_var, x))
        y = float(factual.get(main_var, x))
        return [
            {"x": x, "cf": cf, "y": y},
            {"x": max(0.0, x - 0.02), "cf": cf, "y": y},
            {"x": min(1.0, x + 0.02), "cf": cf, "y": y},
        ]

    def set_organism_id(self, organism_id: str) -> None:
        """Fija el namespace de identidad (genoma) para la experiencia cross-vida.

        B41: el kernel soberano REEMPLAZA el organism_id acuñado por el runner con el
        genoma real; se propaga también a la trayectoria para que la identidad del
        organismo sea única en todo el runner (no queda el org-acuñado del constructor).
        Si llega vacío, se conserva el acuñado por la SSOT (nunca vuelve a run_id).
        """
        if organism_id:
            requested = str(organism_id)
            if requested != self._organism_id:
                if self._dynamic_chain.transition_index:
                    raise ValueError("cannot_change_organism_after_dynamic_life_started")
                self._dynamic_chain = DynamicLifeChain(
                    organism_id=requested,
                    lineage_id=self._lineage.lineage_id,
                    run_id=self.run_id,
                )
                self._adaptive_states = AdaptiveStateStore(
                    organism_id=requested,
                    lineage_id=self._lineage.lineage_id,
                )
            self._organism_id = requested
            self._organism_trajectory.organism_id = self._organism_id

    def set_experience_lessons(self, lessons: List[Dict[str, Any]] | None) -> None:
        """Inyecta lecciones del maestro (7B) para sesgar el razonamiento vía IND."""
        self._experience_lessons = list(lessons) if lessons else []

    def set_causal_context(self, causal_context: Dict[str, Any] | None) -> None:
        """Inyecta el sobre CausalContext.v1 del step (aditivo, gated por el kernel).

        None ⇒ no-op byte-idéntico. Cuando está presente, su ``trace_group_id`` ata la
        cadena decisión→episodio→traza→certificado de ESTE step y viaja como clave
        aditiva en el evento ``episode.closed`` y en el contexto de razonamiento.
        """
        self._causal_context = dict(causal_context) if causal_context else None

    def set_neural_config(self, config: NeuralRuntimeConfig) -> None:
        """Inyecta desde LifeKernel modo, recursos y límites N0 sin duplicar lógica."""

        if self._neural.config != config:
            self._neural = SymbioticNeuralCoordinator(storage=self.storage, config=config)

    def export_neural_state(self) -> Dict[str, Any]:
        """Checkpoint aditivo N3 + cadena vital; no incluye modelos ni buffers."""

        return {
            "schema_version": "neural-organism-checkpoint-v2",
            "n3_temporal_state": self._neural.export_temporal_state(),
            "dynamic_chain": self._dynamic_chain.export_checkpoint(),
            "adaptive_state": self._adaptive_states.export_checkpoint(),
            "contract_versions": {
                "symbiosis_trace": "neural-symbiosis-trace-v2",
                "consumer_receipt": "neural-consumer-receipt-v1",
                "dynamic_state": "organism-dynamic-state-v1",
                "life_transition": "organism-life-transition-v1",
            },
        }

    def restore_neural_state(self, payload: Dict[str, Any] | None) -> int:
        """Restaura continuidad o abre epoch explícita para checkpoint N3 legacy."""

        data = dict(payload or {})
        if data.get("schema_version") == "neural-organism-checkpoint-v2":
            restored = self._neural.restore_temporal_state(data.get("n3_temporal_state"))
            self._dynamic_chain.restore_checkpoint(data.get("dynamic_chain"))
            self._adaptive_states.restore_checkpoint(data.get("adaptive_state"))
            return restored
        restored = self._neural.restore_temporal_state(data)
        self._dynamic_chain.restore_checkpoint(None)
        return restored

    def build_dynamic_trajectory_window(self, *, size: int = 8):
        """Vista longitudinal cerrada sobre la cadena vital verificada."""

        return TrajectoryWindowBuilder(
            self._dynamic_chain.transitions,
            chain_epoch=self._dynamic_chain.chain_epoch,
        ).latest(size=size)

    def replay_dynamic_trajectory(self, *, organ_id: str, size: int = 8) -> Dict[str, Any]:
        """Evalúa un adapter en shadow sin tocar mundo, memoria ni cadena."""

        window = self.build_dynamic_trajectory_window(size=size)
        return ShadowTrajectoryReplay().replay(window, organ_id=organ_id)

    def _regime_snapshot(self) -> Dict[str, Any]:
        current = get_regime_for_scenario(self.scenario.config.name)
        previous_id = (
            (self._dynamic_chain.last_state.regime or {}).get("regime_id")
            if self._dynamic_chain.last_state is not None
            else None
        )
        comparison = None
        if current is not None and previous_id in REGIME_REGISTRY:
            comparison = compare_regimes(REGIME_REGISTRY[previous_id], current)
        return {
            "regime_id": current.regime_id if current is not None else None,
            "regime_model_version": "runtime-regime-model-v1" if current is not None else None,
            "equilibrium_class": current.equilibrium_class if current is not None else None,
            "recovery_profile": current.recovery_profile if current is not None else None,
            "compatibility_with_previous_regime": (
                comparison.compatibility if comparison is not None else "not_applicable"
            ),
            "structural_distance": comparison.structural_distance if comparison else None,
            "transport_feasibility": comparison.transport_feasibility if comparison else None,
            "regime_transition_type": (
                "same" if comparison and comparison.compatibility == "same_regime"
                else "changed" if comparison is not None else "genesis_or_unmapped"
            ),
            "measurement_status": "measured" if current is not None else "unmeasured",
        }

    def _build_dynamic_state(
        self,
        *,
        episode_id: str,
        logical_time: int,
        previous_state_hash: str | None,
        organism_state: OrganismState,
        observation: Mapping[str, Any],
        world_state: Mapping[str, Any],
        scenario_metadata: Mapping[str, Any],
        neural_trace: Mapping[str, Any],
        memory_hits: list[dict[str, Any]],
        memory_write_refs: tuple[str, ...],
        n5_sign_ids: list[str],
        reasoning: Mapping[str, Any],
        viability: Mapping[str, Any] | None,
        certificate: Mapping[str, Any] | None,
        active_action: str | None,
    ) -> OrganismDynamicState:
        organ_rows = list(neural_trace.get("organs") or ())
        n3 = next((row for row in organ_rows if row.get("organ") == "N3"), {})
        regime = self._regime_snapshot()
        resources = {
            name: measured(self._resource_signals.get(name))
            for name in (
                "cpu_pressure", "memory_pressure", "vram_pressure",
                "thermal_pressure", "gpu_temperature_c",
            )
        }
        resources.update(
            {
                "msrc_scale_id": measured(self._resource_signals.get("msrc_scale_id")),
                "msrc_budget_available": measured(
                    self._resource_signals.get("msrc_budget_available")
                ),
                "compute_tier": measured(self._resource_signals.get("compute_tier")),
            }
        )
        viability_payload = dict(viability or {})
        cert_payload = dict(certificate or {})
        return OrganismDynamicState.create(
            organism_id=self._organism_id,
            lineage_id=self._lineage.lineage_id,
            run_id=self.run_id,
            episode_id=episode_id,
            life_step=int(organism_state.episode_count),
            logical_time=logical_time,
            previous_state_hash=previous_state_hash,
            world={
                "scenario_id": self.scenario.config.name,
                "scenario_version": scenario_metadata.get("scenario_version"),
                "scenario_config_hash": canonical_hash(scenario_metadata),
                "observation_hash": canonical_hash(observation),
                "world_state_hash": canonical_hash(world_state),
                "main_variable": self.scenario.config.main_variable,
                "observable_alarm": observation.get("alarm"),
            },
            regime=regime,
            organism={
                "organism_state_id": organism_state.state_id,
                "organism_state_hash": canonical_hash(organism_state.to_dict()),
                "viability": measured(viability_payload.get("viability_margin")),
                "continuity": measured(organism_state.belief.trace_integrity_confidence),
                "risk": measured(cert_payload.get("risk_score")),
                "closure": measured(cert_payload.get("verdict")),
                "active_action": active_action,
                "checkpoint_reference": None,
            },
            memory={
                "mfm_read_set_hashes": [canonical_hash(item) for item in memory_hits],
                "mfm_write_set_hashes": [],
                "smg_snapshot_reference_hash": canonical_hash(self.smg.snapshot()),
                "smg_write_references": list(n5_sign_ids),
                "experience_read_set": [
                    canonical_hash(item) for item in self._experience_lessons
                ],
                "experience_write_set": list(memory_write_refs),
                "n3_state_hash": canonical_hash(n3.get("candidate")) if n3 else None,
                "memory_namespace": self._organism_id,
            },
            neural={
                "active_organs": [
                    row.get("organ") for row in organ_rows if row.get("effective_mode") != "off"
                ],
                "contract_versions": dict(neural_trace.get("organ_contract_versions") or {}),
                "backend_reference_ids": dict(neural_trace.get("backend_identities") or {}),
                "manifest_hashes": {
                    row.get("organ"): row.get("manifest_sha256") for row in organ_rows
                },
                "effective_modes": {
                    row.get("organ"): row.get("effective_mode") for row in organ_rows
                },
                "authority_ceilings": {
                    row.get("organ"): row.get("authority_ceiling") for row in organ_rows
                },
                "adaptation_state_hash": self._adaptive_states.state_hash,
                "adaptation_measurement_status": (
                    "measured" if self._adaptive_states.state_hash is not None else "unmeasured"
                ),
            },
            policy={
                "scheduler_mode": self.reasoning_mode,
                "scheduler_version": "meta-scheduler-runtime",
                "reasoning_profile": self.closure_profile,
                "active_overlays": [
                    family for family in reasoning.get("sequence") or ()
                    if str(family).upper() not in {"ABD", "ANA", "CAU", "CTF", "DED", "PROB"}
                ],
                "reward_guided_state_version": (
                    "reward-guided-runtime-v1" if self._reward_guided is not None else None
                ),
                "autoevolution_knobs": {
                    "memory_retrieval_limit": self.memory_retrieval_limit,
                    "memory_filter_mode": self.memory_filter_mode,
                },
                "autoevolution_version": "autoevolution-runtime",
            },
            resources=resources,
            homeostasis={
                "alarm": observation.get("alarm"),
                "viability_margin": measured(viability_payload.get("viability_margin")),
                "distance_to_edge": measured(viability_payload.get("distance_to_edge")),
                "rollback_required": viability_payload.get("rollback_required"),
            },
        )

    def _symbiosis_identity(
        self,
        *,
        episode_id: str,
        scenario_metadata: Dict[str, Any],
    ) -> SymbiosisIdentity:
        causal = self._causal_context or {}
        scenario_id = (
            f"{scenario_metadata.get('scenario_name', self.scenario.config.name)}"
            f"@{scenario_metadata.get('scenario_version', 'unknown')}"
        )
        return SymbiosisIdentity(
            trace_group_id=str(causal.get("trace_group_id") or f"trace-{episode_id}"),
            organism_id=str(causal.get("organism_id") or self._organism_id),
            lineage_id=str(causal.get("lineage_id") or self._lineage.lineage_id),
            run_id=str(causal.get("run_id") or self.run_id),
            episode_id=episode_id,
            scenario_id=scenario_id,
            decision_id=causal.get("decision_id"),
        )

    def _causal_context_signals(self) -> Dict[str, Any]:
        """Señales aditivas del sobre para el contexto de razonamiento (trazas)."""
        ctx = self._causal_context
        if not ctx:
            return {}
        tg = ctx.get("trace_group_id")
        return {"trace_group_id": tg} if tg else {}

    def _situation_signature(self, observation) -> str:
        """Firma de situación estable, consistente entre sesgo y grabación."""
        from runtime.organism.experience import situation_key

        regime = "alarm" if getattr(observation, "alarm", False) else "calm"
        return situation_key(
            scenario=self.scenario.config.name,
            regime=regime,
            main_variable=self.scenario.config.main_variable,
        )

    def _experience_biased_intervention(self, observation, intervention):
        """Si esta intervención hirió antes en esta situación, propone una mejor.

        Umbral de dolor mínimo + margen de mejora ⇒ el organismo solo cambia cuando
        hay una alternativa claramente menos dolorosa; nunca veto absoluto. La
        fuerza es proporcional a la cicatriz (más dolor ⇒ más probable superar el margen).
        """
        _MIN_SCAR = 0.5
        _MARGIN = 0.25
        sig = self._situation_signature(observation)
        wisdom = self._experience.wisdom(organism_id=self._organism_id, situation=sig)
        scar_here = float(wisdom.scar.get(intervention, 0.0))
        if scar_here < _MIN_SCAR:
            return None
        candidates = [iv for iv in self.scenario.config.interventions if iv != intervention]
        if not candidates:
            return None
        best = min(candidates, key=lambda iv: float(wisdom.scar.get(iv, 0.0)))
        if float(wisdom.scar.get(best, 0.0)) + _MARGIN < scar_here:
            return best
        return None

    def set_external_reasoner_enabled(self, enabled: bool) -> None:
        """Habilita/inhabilita el razonador externo para el próximo episodio.

        Es una condición NECESARIA pero no suficiente: el scheduler solo agenda
        ``ext_open_thinker`` si además el perfil admitido y el gate lo permiten.
        """
        self._external_reasoner_enabled = bool(enabled)

    def set_resource_signals(self, snapshot: Dict[str, Any] | None) -> None:
        """Inyecta el snapshot de recursos host+GPU del ciclo vital actual.

        Se traduce en señales de presión (cpu/mem/vram/thermal/gpu) dentro del
        contexto de razonamiento para que ``extract_context_features`` y el
        presupuesto reaccionen al hardware real. Snapshot vacío -> sin efecto.
        """
        self._resource_signals = dict(snapshot) if snapshot else {}

    def _resource_context_signals(self) -> Dict[str, Any]:
        """Mapea el snapshot de recursos a las claves que consume el scheduler."""
        snap = self._resource_signals
        if not snap:
            return {}
        signals: Dict[str, Any] = {}
        for key in (
            "cpu_pressure",
            "memory_pressure",
            "vram_pressure",
            "thermal_pressure",
            "gpu_load",
        ):
            if isinstance(snap.get(key), (int, float)):
                signals[key] = float(snap[key])
        if snap.get("gpu_available"):
            signals["gpu_available"] = True
        if isinstance(snap.get("gpu_acceleration"), (int, float)):
            signals["gpu_acceleration_signal"] = float(snap["gpu_acceleration"])
        if isinstance(snap.get("vram_headroom"), (int, float)):
            signals["vram_headroom"] = float(snap["vram_headroom"])
        return signals

    def run_episode(self, *, external_input: float = 0.04) -> Dict[str, Any]:
        """Ejecuta un episodio cognitivo completo.

        Args:
            external_input: Entrada/perturbación externa para el escenario.

        Returns:
            Dict con episodio, smg_snapshot, reasoning, artifact, certification.
        """
        episode_id = f"episode-{uuid4()}"
        scenario_metadata = self._build_scenario_metadata()

        # 1. Observar escenario
        observation = self.scenario.observe()
        observation_dict = self.scenario.to_observation_dict(observation)
        observation_ref = self.smg.add_observation(observation_dict)

        # 2. Crear signo principal
        main_proposition = self.scenario.get_main_proposition(observation)
        sign_main = self.smg.create_sign(
            proposition=main_proposition,
            observation_id=observation_ref.observation_id,
            metadata={self.scenario.config.main_variable: observation.state.get(
                self.scenario.config.main_variable
            )},
        )

        # 3. Generar y verificar fórmula LOTF
        formula = self.scenario.get_formula(observation)
        ast = self.lotf.parse(formula)
        self.lotf.check(ast, self.scenario.config.type_context)

        # 4. Consultar memoria
        memory_hits = self.memory_retrieval.retrieve(
            run_id=self.run_id,
            query={
                "proposition": main_proposition,
                "alarm": observation.alarm,
            },
            limit=self.memory_retrieval_limit,
            scenario_name=scenario_metadata["scenario_name"],
            scenario_filter_mode=self.memory_filter_mode,
        )

        # 5. Seleccionar intervención
        intervention = self.scenario.select_intervention(observation)
        if memory_hits:
            top = memory_hits[0].get("structure", {})
            if top.get("relation_kind") == "support" and observation.alarm:
                # Memoria soporta la intervención por alarma
                intervention = self.scenario.select_intervention(observation)
        # E3 — sabiduría ∝ daño: si esta situación ya lo hirió con esta intervención
        # y hay una alternativa con claramente menos dolor recordado, la evita (no
        # repetir errores). Fuerza proporcional a la cicatriz. RNFE_EXPERIENCE off ⇒ no-op.
        self._experience_bias = None
        if self._experience is not None:
            alternative = self._experience_biased_intervention(observation, intervention)
            if alternative is not None and alternative != intervention:
                self._experience_bias = {"avoided": intervention, "chose": alternative}
                intervention = alternative

        # 6. Simular contrafactual (sin intervención o con opuesta)
        counter_intervention = (
            self.scenario.config.interventions[1]
            if len(self.scenario.config.interventions) > 1
            else self.scenario.config.interventions[0]
        )
        counterfactual = self.scenario.simulate_counterfactual(
            intervention=counter_intervention,
            external_input=external_input,
        )

        # 7. Computar la transición factual (greedy) por SIMULACIÓN (sin mutar). La
        # acción FINAL se aplica una sola vez tras la decisión de override (paso 9c), de
        # modo que el override REEMPLACE al greedy desde el estado pre-acción — no lo
        # apile — y los efectos colaterales ocultos del greedy (p.ej. deuda acumulada)
        # no se comprometan si la acción fue reemplazada.
        factual = self.scenario.simulate_counterfactual(
            intervention=intervention,
            external_input=external_input,
        )

        # 8. Crear signo de intervención y relación
        intervention_proposition = self.scenario.get_intervention_proposition(intervention)
        sign_intervention = self.smg.create_sign(
            proposition=intervention_proposition,
            observation_id=observation_ref.observation_id,
            metadata={"intervention": intervention},
        )

        relation_kind = self.scenario.evaluate_relation_kind(
            factual=factual,
            counterfactual=counterfactual,
        )
        relation = self.smg.link_signs(
            source_sign_id=sign_main.sign_id,
            target_sign_id=sign_intervention.sign_id,
            kind=relation_kind,
            metadata={
                f"factual_{self.scenario.config.main_variable}": factual.state.get(
                    self.scenario.config.main_variable
                ),
                f"counterfactual_{self.scenario.config.main_variable}": counterfactual.state.get(
                    self.scenario.config.main_variable
                ),
            },
        )
        counterfactual_dict = self.scenario.to_transition_dict(counterfactual)
        updated_world = self.scenario.to_transition_dict(factual)
        belief_input = asdict(self._previous_belief) if self._previous_belief else None
        causal_attestation = build_causal_attestation(
            scenario_name=scenario_metadata["scenario_name"],
            scenario_version=scenario_metadata.get("scenario_version"),
            main_variable=self.scenario.config.main_variable,
            intervention=intervention,
            observation=observation_dict,
            factual=updated_world,
            counterfactual=counterfactual_dict,
            relation_kind=relation_kind,
            signature=self.scenario.causal_signature,
        )

        # 8b. Simbiosis pre-razonamiento: N5 estructura la observación y alimenta
        # SMG/MFM; N3 actualiza continuidad; N1 y N4 producen propuestas shadow.
        symbiosis_identity = self._symbiosis_identity(
            episode_id=episode_id,
            scenario_metadata=scenario_metadata,
        )
        neural_signals = self._neural.begin_episode(
            identity=symbiosis_identity,
            observation=observation_dict,
            formula=formula,
            proposition=main_proposition,
            memory_hits=memory_hits,
            scenario_metadata=scenario_metadata,
            causal_attestation=causal_attestation,
            resources=self._resource_signals,
        )
        # Copia: los resultados del consumidor no deben mutar el candidato hasheado.
        n5_ingestion = dict(neural_signals.get("n5_ingestion") or {})
        n5_sign_ids = []
        for chunk in n5_ingestion.get("chunks", []):
            content = str(chunk.get("text") or "").strip()
            if not content:
                continue
            offsets = chunk.get("offsets") or {}
            byte_offsets = offsets.get("byte") or {}
            chunk_sign = self.smg.create_sign(
                proposition=content,
                observation_id=observation_ref.observation_id,
                metadata={
                    "origin": "N5",
                    "chunk_index": chunk.get("index"),
                    "byte_start": byte_offsets.get("start"),
                    "byte_end": byte_offsets.get("end"),
                    "trace_group_id": symbiosis_identity.trace_group_id,
                },
            )
            n5_sign_ids.append(chunk_sign.sign_id)
            self.smg.link_signs(
                source_sign_id=chunk_sign.sign_id,
                target_sign_id=sign_main.sign_id,
                kind="support",
                metadata={"origin": "N5", "consumer": "SMG"},
            )
        n5_ingestion["smg_sign_ids"] = n5_sign_ids
        if self._neural.organ_has_candidate(episode_id, "N5"):
            self._neural.record_consumer_receipt(
                episode_id=episode_id,
                organ="N5",
                consumer_id="smg_write_result",
                consumer_input={"chunks": n5_ingestion.get("chunks", [])},
                consumer_output={"smg_sign_ids": n5_sign_ids},
                verdict_class=(
                    ConsumerVerdictClass.ACCEPTED
                    if n5_sign_ids
                    else ConsumerVerdictClass.UNAVAILABLE
                ),
                verdict_detail="written" if n5_sign_ids else "no_nonempty_chunks",
                evidence_refs=tuple(f"smg:{sign_id}" for sign_id in n5_sign_ids) or ("smg:no-write",),
            )
            self._neural.record_consumer_receipt(
                episode_id=episode_id,
                organ="N5",
                consumer_id="mfm_candidate_gate",
                consumer_input={"memory_candidates": n5_ingestion.get("memory_candidates", [])},
                consumer_output={"promotion": "requires_existing_mfm_gate", "direct_write": False},
                verdict_class=ConsumerVerdictClass.OBSERVED,
                verdict_detail="candidate_deferred_to_existing_gate",
                evidence_refs=("MFM",),
            )

        # 9. Ejecutar scheduler de razonamiento
        reasoning_context = build_reasoning_context(
            episode_id=episode_id,
            run_id=self.run_id,
            observation=observation_dict,
            intervention=intervention,
            formula=formula,
            memory_hits=memory_hits,
            counterfactual=counterfactual_dict,
            updated_world=updated_world,
            relation_kind=relation_kind,
            scenario=self.scenario.config.name,
            scenario_metadata=scenario_metadata,
            belief_state=belief_input,
            closure_profile=self.closure_profile,
            reasoning_mode=self.reasoning_mode,
            extra_signals={
                "memory_filter_mode": self.memory_filter_mode,
                "causal_attestation": causal_attestation,
                "neural_symbiosis_signals": neural_signals,
                **self._resource_context_signals(),
                **self._causal_context_signals(),
            },
        )
        overlay_directives: Dict[str, str] | None = None
        if self._reward_guided is not None:
            overlay_directives = self._reward_guided.directives(
                self.run_id, regime=self._trajectory_regime_label
            )
            reasoning_context["overlay_directives"] = overlay_directives
        # Reglas transferidas por la ecología (modo reasoning_policy_plus_rules):
        # IND las consulta en su rama a-priori. Sin ecología quedan en None.
        if self._inherited_rules:
            reasoning_context["inherited_rules"] = self._inherited_rules
        # C4: tier_3 pidió el razonador externo. Solo se solicita el perfil admitido
        # cuando además RNFE_EXTERNAL_REASONER_RUNTIME está on; el scheduler agenda
        # ext_open_thinker solo si el régimen valida la admisión, y degrada si no
        # (nunca crashea). Sin ambos flags -> perfil nominal (byte-idéntico).
        if self._external_reasoner_enabled and _external_reasoner_runtime_flag():
            reasoning_context["family_profile"] = "core_plus_external_reasoner_gated_v1"
            reasoning_context.setdefault("regime_hint", self._trajectory_regime_label)
        reasoning = self.scheduler.run(reasoning_context)
        neural_comparisons = self._neural.consume_reasoning(
            episode_id=episode_id,
            reasoning=reasoning,
            lotf_valid=True,
        )

        # 9b. Override determinista guardado (actuación del razonamiento). Gated por
        # RNFE_REASONING_ACTUATES=1 (sombra OFF ⇒ camino nominal byte-idéntico). En
        # conflicto causal-contrafactual, si una familia recomienda la alterna y la
        # guarda certifica que es mejor (el contrafactual ya está simulado), se adopta.
        intervention_override, candidate_transition = self._maybe_override_intervention(
            reasoning_state=reasoning.get("state") or {},
            greedy_intervention=intervention,
            factual=factual,
            external_input=external_input,
        )
        if intervention_override.fired and candidate_transition is not None:
            # Conmutar: la alterna recomendada (simulada fresca) pasa a ser la
            # factual; el resultado greedy queda como contrafactual.
            counterfactual = factual
            counter_intervention = intervention
            factual = candidate_transition
            intervention = intervention_override.to_intervention
            relation_kind = self.scenario.evaluate_relation_kind(
                factual=factual, counterfactual=counterfactual
            )
            intervention_proposition = self.scenario.get_intervention_proposition(intervention)
            sign_intervention = self.smg.create_sign(
                proposition=intervention_proposition,
                observation_id=observation_ref.observation_id,
                metadata={"intervention": intervention, "via": "override"},
            )
            relation = self.smg.link_signs(
                source_sign_id=sign_main.sign_id,
                target_sign_id=sign_intervention.sign_id,
                kind=relation_kind,
                metadata={
                    f"factual_{self.scenario.config.main_variable}": factual.state.get(
                        self.scenario.config.main_variable
                    ),
                    f"counterfactual_{self.scenario.config.main_variable}": counterfactual.state.get(
                        self.scenario.config.main_variable
                    ),
                    "intervention_override": True,
                },
            )
            counterfactual_dict = self.scenario.to_transition_dict(counterfactual)
            updated_world = self.scenario.to_transition_dict(factual)
            causal_attestation = build_causal_attestation(
                scenario_name=scenario_metadata["scenario_name"],
                scenario_version=scenario_metadata.get("scenario_version"),
                main_variable=self.scenario.config.main_variable,
                intervention=intervention,
                observation=observation_dict,
                factual=updated_world,
                counterfactual=counterfactual_dict,
                relation_kind=relation_kind,
                signature=self.scenario.causal_signature,
            )
            self.storage.append_event(
                event_type="reasoning.intervention_override",
                run_id=self.run_id,
                source="scenario_episode_runner",
                payload={"episode_id": episode_id, **intervention_override.to_dict()},
            )

        # 9c. Aplicar la acción FINAL una sola vez desde el estado pre-acción. Hasta aquí
        # nada mutó el escenario (greedy y candidatas se computaron por simulación); esta
        # es la ÚNICA mutación que avanza el mundo, por la intervención efectivamente
        # elegida (greedy o la del override). Byte-idéntico con actuación OFF (final=greedy).
        self.scenario.factual_transition(
            intervention=intervention, external_input=external_input
        )

        # 10. Construir payload de episodio
        factual_delta = float(factual.state.get(self.scenario.config.main_variable, 0.0)) - float(
            observation.state.get(self.scenario.config.main_variable, 0.0)
        )
        counterfactual_delta = float(counterfactual.state.get(self.scenario.config.main_variable, 0.0)) - float(
            observation.state.get(self.scenario.config.main_variable, 0.0)
        )
        episode_payload = {
            "episode_id": episode_id,
            "timestamp": utc_now_iso(),
            "scenario": self.scenario.config.name,
            "scenario_metadata": scenario_metadata,
            "closure_profile": self.closure_profile,
            "context": {
                "observation": observation_dict,
                "formula": formula,
                "intervention": intervention,
                "counterfactual": counterfactual_dict,
                "retrieved_memory": memory_hits,
                "memory_rag_attestation": reasoning_context.get("memory_rag_attestation"),
                "memory_filter_mode": self.memory_filter_mode,
                "causal_attestation": causal_attestation,
                "neural_ingestion": n5_ingestion,
                "neural_temporal_state": neural_signals.get("n3_temporal"),
                "neural_trace_group_id": symbiosis_identity.trace_group_id,
                "closure_profile": self.closure_profile,
            },
            "result": {
                "updated_world": updated_world,
                "relation_kind": relation_kind,
                "reasoning_sequence": reasoning["sequence"],
                "factual_delta": factual_delta,
                "counterfactual_delta": counterfactual_delta,
                "intervention_effect": relation_kind,
                "alarm_transition": observation.alarm,
                "neural_comparisons": neural_comparisons,
            },
            "trace": reasoning["trace"],
        }

        # 11. Persistir evento de cierre. B41: el sobre CausalContext viaja como clave
        # aditiva (gated). Ausente ⇒ episode_payload byte-idéntico a pre-B41.
        if self._causal_context is not None:
            episode_payload["causal_context"] = self._causal_context
        self.storage.append_event(
            event_type="episode.closed",
            payload=episode_payload,
            run_id=self.run_id,
            source="scenario_episode_runner",
        )

        # 12. Materializar artifact
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
            metadata={
                "episode_id": episode_id,
                "scenario": self.scenario.config.name,
                "scenario_metadata": scenario_metadata,
            },
        )

        episode_result = {
            "episode": episode_payload,
            "smg_snapshot": self.smg.snapshot(),
            "reasoning": reasoning,
            "artifact": asdict(artifact),
            "run_id": self.run_id,
            "intervention_override": intervention_override.to_dict(),
        }

        # 12b. Build and persist belief state
        current_belief = build_belief_state(episode_result=episode_result)
        belief_prior = self._previous_belief
        episode_result["belief_state"] = {
            "prior": asdict(belief_prior) if belief_prior else None,
            "posterior": asdict(current_belief),
        }
        self._previous_belief = current_belief

        # 12c. T5 SOVEREIGNTY: Transition organism state and append to trajectory
        #
        # ORDEN DEL CICLO, medido: la transición corre AQUÍ (12c) y el certificado
        # no se emite hasta el paso 13, ~90 líneas más abajo. `TrajectoryStateMachine`
        # lee `episode_result["certification"]["verdict"]` (trajectory_state_machine.py:34)
        # y en este punto esa clave NO EXISTE todavía, así que `is_certified` es False
        # SIEMPRE. Consecuencia medida: margen −0.03 y degradación +0.02 en cada
        # episodio de la vida del organismo, mientras los 25/25 certificados emitidos
        # decían `certified`. El organismo se castigaba por acertar, hasta morir en
        # el paso ~32. Con `trajectory_reward="previous_certificate"` se le entrega
        # el último veredicto emitido: recompensa con un paso de retardo, que es la
        # única que existe en este punto. Default "none" = conducta histórica.
        if self._trajectory_reward == "previous_certificate" and self._last_certification:
            episode_result["certification"] = dict(self._last_certification)
        previous_state = self._organism_state
        # B41: el state_id se ancla al GENOMA (organism_id), no a la corrida (run_id) —
        # coherente con la génesis del kernel (state-0-{organism_id}).
        new_state_id = f"state-{self._organism_state.episode_count + 1}-{self._organism_id}"
        regime = self._trajectory_regime_label

        self._organism_state = transition_organism_state(
            current=self._organism_state,
            episode_result=episode_result,
            regime=regime,
            new_state_id=new_state_id,
            timestamp=utc_now_iso(),
        )

        # Validate and assess viability
        constitutional_validation = self._constitution.validate(self._organism_state)
        viability_assessment = self._viability_kernel.assess(
            state=self._organism_state,
            previous_state=previous_state,
        )

        # Append to trajectory
        self._organism_trajectory.append_point(
            state=self._organism_state,
            regime=regime,
            episode_id=episode_id,
            timestamp=utc_now_iso(),
            constitutional_validation=constitutional_validation,
            viability_margin=viability_assessment.viability_margin,
        )

        # Add trajectory to episode result for certification
        episode_result["organism_trajectory"] = self._organism_trajectory.to_dict()
        episode_result["trajectory_window"] = self._organism_trajectory.get_window(
            window_size=5
        ).to_dict()
        episode_result["constitutional_validation"] = {
            "is_valid": constitutional_validation.is_valid,
            "verdict": constitutional_validation.verdict,
            "hard_violation_count": constitutional_validation.hard_violation_count,
            "soft_violation_count": constitutional_validation.soft_violation_count,
            "margin_to_threshold": constitutional_validation.margin_to_threshold,
        }
        episode_result["viability_assessment"] = {
            "is_viable": viability_assessment.is_viable,
            "viability_margin": viability_assessment.viability_margin,
            "distance_to_edge": viability_assessment.distance_to_edge,
            "rollback_required": viability_assessment.rollback_required,
        }
        # N6 observa evidencia viva y solo produce/evalúa una propuesta shadow. El
        # bloque completo entra al certificado como metadata aditiva sin cambiar su
        # veredicto ni su candidatura de promoción.
        episode_result["neural_symbiosis"] = self._neural.prepare_certification(
            episode_id=episode_id,
            viability=episode_result["viability_assessment"],
            reasoning=reasoning,
        )

        # 12e. P9.6 — MEDIR, NO FABRICAR.
        # Los productores existían (`compute_belief_shift`, `compute_transition_vector`) y
        # NADIE los llamaba en el camino vivo: `process_episode` se invocaba pelado y el
        # certificador rellenaba los huecos con valores favorables (purity=1.0,
        # stability=1.0, kl=0.0, policy=0.5). El organismo no medía: se auto-declaraba sano
        # por ausencia de datos. Acá se computan con lo que YA está en la mano.
        #
        # Lo que genuinamente NO existe en este punto NO se inventa:
        #   - `reality_assessment`: nadie lo construye en el camino vivo (solo el bench,
        #     `runtime/reality/service.py`). Se deja ausente; el colapso lo detecta el
        #     propio gate con los datos que sí tiene (P9.6 paso 4).
        #   - transición CROSS-escenario: el kernel destruye el runner al cambiar de
        #     escenario, así que este runner solo puede observar transiciones intra.
        belief_shift = (
            compute_belief_shift(prior=belief_prior, posterior=current_belief)
            if belief_prior is not None
            else None  # primer episodio: no hay prior. Ausencia, no un cero favorable.
        )
        # Import diferido: `runtime.reality.transition_analysis` importa
        # `runtime.world.compatibility`, y `runtime.world.__init__` importa este módulo —
        # a nivel de módulo sería un ciclo. Mismo patrón que `promotion_gate.assess_transfer`.
        from runtime.reality.transition_analysis import compute_transition_vector

        retrieval_metrics = retrieval_metrics_from_hits(memory_hits)
        transition_vector = None
        if self._previous_result is not None:
            transition_vector = compute_transition_vector(
                previous_result=self._previous_result,
                current_result=episode_result,
                compatibility=self._self_compatibility(),
                retrieval_metrics=retrieval_metrics,
            )

        # 13. Certificación
        certification = self.promotion_gate.process_episode(
            run_id=self.run_id,
            episode_result=episode_result,
            transition_vector=transition_vector,
            belief_shift=belief_shift,
            retrieval_metrics=retrieval_metrics,
        )
        # El resumen se escribía SOLO en el dict de retorno (`{**episode_result, ...}`),
        # así que ningún consumidor del `episode_result` vivo lo veía nunca: ni
        # `trajectory_state_machine.py:34` (veredicto), ni `vitals.py:215`
        # (certificate_id), ni `reality/belief_state.py:197`. Se escribe en sitio.
        cert_summary = {
            "certificate_id": certification["certificate"].certificate_id,
            "verdict": certification["certificate"].verdict,
            "promotion_candidate": certification["certificate"].promotion_candidate,
            "decision_verdict": certification["decision"].verdict,
        }
        episode_result["certification"] = dict(cert_summary)
        self._last_certification = dict(cert_summary)
        self._previous_result = episode_result

        # 13b. R2 — lazo de autoevolución (ρₜ): el organismo observa su propio
        # certificado y decide si proponerse una modificación, monitorear una
        # activa, o ejecutar rollback al último checkpoint sano.
        evolution = self._autoevolution.observe_episode(
            organism_state=self._organism_state,
            episode_result=episode_result,
            certificate_metadata=certification["certificate"].metadata,
            certificate_verdict=certification["certificate"].verdict,
        )
        restored_state = evolution.pop("restored_state", None)
        if restored_state is not None:
            self._organism_state = restored_state
        episode_result["autoevolution"] = evolution
        episode_result["lineage"] = self._lineage.to_dict()

        # 13c. R3 — recompensa semi-Markov del razonamiento: el escalar de control
        # r = ΔIoC − λE·(coste/presupuesto) − λB·B_safe, reusando ΔIoC y B_safe del
        # certificado (R1) y el coste del trace. Se adjunta, persiste y — con
        # RNFE_REWARD_GUIDED_SELECTION=1 — GOBIERNA la ecología opcional del
        # siguiente episodio (selector guiado-por-recompensa).
        from runtime.reasoning.scheduler_meta.reward import (
            compute_episode_reward,
            reasoning_cost_from_trace,
        )

        cert_meta = certification["certificate"].metadata or {}
        cert_risk_plus = cert_meta.get("risk_plus") or {}
        # Efectividad del mundo: margen de seguridad del resultado factual
        # (committed, post-override) en la dirección de optimización. Cierra la
        # ceguera de ΔIoC*; pesa solo con RNFE_REWARD_LAMBDA_EFFECTIVENESS>0.
        try:
            effectiveness = outcome_effectiveness(
                value=float(factual.state.get(self.scenario.config.main_variable, 0.0)),
                alarm_threshold=float(self.scenario.config.alarm_threshold),
                alarm_semantics=str(self.scenario.causal_signature.alarm_semantics),
            )
        except Exception:
            effectiveness = None
        # ν = cau.helps_goal (¿la acción factual va en la dirección del objetivo?),
        # ya direction-aware desde core_inference. Criterio de viabilidad de primera
        # clase (cura J(h|X)); pesa solo con RNFE_REWARD_LAMBDA_NU>0.
        nu_helps_goal = ((reasoning.get("state") or {}).get("cau_link") or {}).get("helps_goal")
        reasoning_reward = compute_episode_reward(
            delta_ioc=cert_risk_plus.get("delta_ioc"),
            delta_ioc_star=(cert_meta.get("omega") or {}).get("delta_ioc_star"),
            reasoning_cost=reasoning_cost_from_trace(reasoning.get("trace") or []),
            cost_budget=reasoning.get("effective_max_steps"),
            b_safe=cert_risk_plus.get("b_safe"),
            effectiveness=effectiveness,
            nu=nu_helps_goal,
        )
        episode_result["reasoning_reward"] = reasoning_reward
        executed_overlays = [
            family.lower()
            for family in (reasoning.get("sequence") or [])
            if family.lower() not in {"abd", "ana", "cau", "ctf", "ded", "prob"}
        ]
        if self._reward_guided is not None:
            self._reward_guided.observe(
                run_id=self.run_id,
                reward_block=reasoning_reward,
                executed_sequence=reasoning.get("sequence") or [],
                regime=regime,
            )
            episode_result["reward_guided"] = {
                "directives": overlay_directives or {},
                "executed_overlays": executed_overlays,
                **self._reward_guided.summary(self.run_id, regime=regime),
            }
        self.storage.append_event(
            event_type="reasoning.reward",
            run_id=self.run_id,
            source="meta_scheduler",
            payload={
                "episode_id": episode_id,
                # Overlays activos + régimen: permiten re-sembrar y estratificar la
                # evidencia del selector guiado-por-recompensa entre runners.
                "optional_overlays_active": executed_overlays,
                "regime_label": regime,
                **reasoning_reward,
            },
        )

        # E1 — Experiencia: destilar ESTE episodio (éxito o golpe) en el diario del
        # organismo, con firma de situación y severidad ∝ daño. RNFE_EXPERIENCE off ⇒ skip.
        if self._experience is not None:
            from runtime.organism.experience import build_experience

            cert = certification["certificate"]
            va = episode_result.get("viability_assessment") or {}
            # Sin `or 1.0`: un margen de viabilidad MEDIDO de 0.0 —el organismo
            # justo en el borde— se leía como 1.0, margen máximo. Y este valor
            # alimenta el delta que alimenta la severidad del lazo de
            # experiencia: el momento de más dolor se registraba como el de menos.
            _pv = getattr(getattr(previous_state, "viability", None), "viability_margin", None)
            if _pv is None:
                _pv = va.get("viability_margin")
            prev_vm = 1.0 if _pv is None else float(_pv)
            vm = float(va.get("viability_margin", prev_vm))
            exp = build_experience(
                organism_id=self._organism_id,
                run_id=self.run_id,
                episode_id=episode_id,
                scenario=self.scenario.config.name,
                regime=("alarm" if getattr(observation, "alarm", False) else "calm"),
                main_variable=self.scenario.config.main_variable,
                causal_status="",
                intervention=intervention,
                viability_margin=vm,
                ioc=float(getattr(cert, "ioc_proxy", 0.0) or 0.0),
                risk=float(getattr(cert, "risk_score", 0.0) or 0.0),
                reward=float(reasoning_reward.get("reward", 0.0) or 0.0),
                action="act",
                certified=(getattr(cert, "verdict", None) == "certified"),
                closure_passed=bool((va.get("is_viable", True))),
                viability_delta=vm - prev_vm,
            )
            self._experience.record(exp)
            episode_result["experience"] = {
                "situation_key": exp.situation_key,
                "severity": exp.severity,
                "wound": exp.wound,
                "biased": self._experience_bias,
            }
            if self._experience_bias is not None:
                self.storage.append_event(
                    event_type="experience.applied",
                    run_id=self.run_id,
                    source="experience",
                    payload={"episode_id": episode_id, "situation_key": exp.situation_key,
                             **self._experience_bias},
                )

        cert = certification["certificate"]
        symbiosis_trace = self._neural.finalize_episode(
            episode_id=episode_id,
            outcome={
                "intervention": intervention,
                "relation_kind": relation_kind,
            },
            certificate={
                "certificate_id": cert.certificate_id,
                "verdict": cert.verdict,
                "promotion_candidate": cert.promotion_candidate,
            },
            reward=reasoning_reward,
        )
        memory_write_refs = tuple(
            [f"smg:{sign_id}" for sign_id in n5_sign_ids]
            + (
                [f"experience:{episode_result['experience']['situation_key']}"]
                if "experience" in episode_result
                else []
            )
        )
        next_transition_index = self._dynamic_chain.transition_index + 1
        state_before = self._build_dynamic_state(
            episode_id=episode_id,
            logical_time=next_transition_index * 2 - 1,
            previous_state_hash=(
                self._dynamic_chain.last_state.state_hash
                if self._dynamic_chain.last_state is not None
                else None
            ),
            organism_state=previous_state,
            observation=observation_dict,
            world_state=observation_dict,
            scenario_metadata=scenario_metadata,
            neural_trace=symbiosis_trace,
            memory_hits=memory_hits,
            memory_write_refs=(),
            n5_sign_ids=[],
            reasoning=reasoning,
            viability={
                "viability_margin": previous_state.viability.viability_margin,
                "distance_to_edge": previous_state.viability.distance_to_edge,
                "rollback_required": False,
            },
            certificate=None,
            active_action=None,
        )
        state_after = self._build_dynamic_state(
            episode_id=episode_id,
            logical_time=next_transition_index * 2,
            previous_state_hash=state_before.state_hash,
            organism_state=self._organism_state,
            observation=observation_dict,
            world_state=updated_world,
            scenario_metadata=scenario_metadata,
            neural_trace=symbiosis_trace,
            memory_hits=memory_hits,
            memory_write_refs=memory_write_refs,
            n5_sign_ids=n5_sign_ids,
            reasoning=reasoning,
            viability=episode_result["viability_assessment"],
            certificate={
                "certificate_id": cert.certificate_id,
                "verdict": cert.verdict,
                "risk_score": getattr(cert, "risk_score", None),
            },
            active_action=intervention,
        )
        organ_candidates = {
            row.get("organ"): row
            for row in symbiosis_trace.get("organs") or ()
            if row.get("organ") in {"N1", "N2", "N4", "N6"}
        }
        life_transition = self._dynamic_chain.commit(
            state_before=state_before,
            state_after=state_after,
            trace_group_id=symbiosis_identity.trace_group_id,
            action_proposals=tuple(
                {
                    "organ": organ,
                    "candidate_hash": row.get("candidate_hash"),
                    "backend_id": (
                        symbiosis_trace.get("backend_identities") or {}
                    ).get(organ),
                    "historical_uncertainty": row.get("uncertainty"),
                    "historical_cost": row.get("cost") or {},
                    "historical_causal_comparison": (
                        (row.get("candidate") or {}).get("canonical_comparison")
                        if isinstance(row.get("candidate"), Mapping)
                        else None
                    ),
                    "effective_mode": row.get("effective_mode"),
                    "authority_ceiling": row.get("authority_ceiling"),
                }
                for organ, row in sorted(organ_candidates.items())
            ),
            authoritative_decision={
                "authority": "MetaScheduler+ScenarioEpisodeRunner",
                "reasoning_sequence": list(reasoning.get("sequence") or ()),
                "intervention_override": intervention_override.to_dict(),
            },
            committed_intervention={"intervention": intervention},
            external_input=external_input,
            factual_outcome={
                "world_state_hash": canonical_hash(updated_world),
                "relation_kind": relation_kind,
                "factual_delta": factual_delta,
            },
            counterfactual_evidence={
                "origin": "C-GWM scenario simulation",
                "world_state_hash": canonical_hash(counterfactual_dict),
                "counterfactual_delta": counterfactual_delta,
                "causal_attestation_hash": canonical_hash(causal_attestation),
            },
            certificate={
                "certificate_id": cert.certificate_id,
                "verdict": cert.verdict,
                "promotion_candidate": cert.promotion_candidate,
            },
            reward=dict(reasoning_reward),
            memory_delta={
                "read_set_hashes": [canonical_hash(item) for item in memory_hits],
                "write_references": list(memory_write_refs),
                "smg_write_references": list(n5_sign_ids),
            },
            neural_state_delta={
                "symbiosis_trace_hash": canonical_hash(symbiosis_trace),
                "n3_before_hash": state_before.memory.get("n3_state_hash"),
                "n3_after_hash": state_after.memory.get("n3_state_hash"),
                "replay_context": {
                    "scenario_id": symbiosis_identity.scenario_id,
                    "inputs": {
                        "observation": observation_dict,
                        "formula": formula,
                        "proposition": main_proposition,
                        "memory_hits": [
                            {"episode_id": item.get("episode_id"), "structure": item.get("structure")}
                            for item in memory_hits[:3]
                        ],
                        "scenario_metadata": scenario_metadata,
                        "causal_attestation": causal_attestation,
                        "resources": dict(self._resource_signals),
                    },
                    "resources": dict(self._resource_signals),
                    "n3_temporal": neural_signals.get("n3_temporal") or {},
                    "reasoning_state": reasoning.get("state") or {},
                    "lotf_valid": True,
                    "viability": episode_result["viability_assessment"],
                    "reasoning": {
                        "sequence": reasoning.get("sequence") or [],
                        "trace": reasoning.get("trace") or [],
                    },
                },
            },
            policy_delta={
                "reasoning_profile": self.closure_profile,
                "executed_overlays": executed_overlays,
                "autoevolution_action": evolution.get("action"),
            },
            resource_delta={
                "before": state_before.resources,
                "after": state_after.resources,
            },
            viability_delta={
                "before": previous_state.viability.viability_margin,
                "after": self._organism_state.viability.viability_margin,
                "delta": (
                    self._organism_state.viability.viability_margin
                    - previous_state.viability.viability_margin
                ),
            },
            regime_before=state_before.regime,
            regime_after=state_after.regime,
            rollback_refuge_result={
                "rollback_required": episode_result["viability_assessment"].get(
                    "rollback_required"
                ),
                "autoevolution": evolution.get("action"),
            },
            storage=self.storage,
        )
        if life_transition.status == "committed":
            symbiosis_trace = self._neural.link_life_transition(
                episode_id=episode_id,
                transition_id=life_transition.transition_id,
                previous_transition_hash=life_transition.previous_transition_hash,
                state_before_hash=state_before.state_hash,
                state_after_hash=state_after.state_hash,
                active_regime=state_after.regime.get("regime_id"),
                memory_write_references=memory_write_refs,
                policy_versions={
                    "scheduler": "meta-scheduler-runtime",
                    "reasoning_profile": self.closure_profile,
                    "autoevolution": "autoevolution-runtime",
                },
            )
            updated_adaptive_states = self._adaptive_states.update(
                life_transition, symbiosis_trace
            )
            adaptation_priorities = self._adaptation_planner.plan(updated_adaptive_states)
            adaptation_payload = {
                "schema_version": "organism-adaptation-update-v1",
                "transition_id": life_transition.transition_id,
                "adaptive_state_hash": self._adaptive_states.state_hash,
                "states": [state.to_dict() for state in updated_adaptive_states],
                "priorities": adaptation_priorities,
                "authority_effect": "none",
            }
            self.storage.append_event(
                event_type="organism.adaptation.updated",
                run_id=self.run_id,
                source="adaptation_planner",
                payload=adaptation_payload,
            )
            episode_result["adaptation"] = adaptation_payload
            episode_result["dynamic_trajectory_window"] = (
                self.build_dynamic_trajectory_window(size=8).to_dict()
            )
        episode_result["dynamic_state"] = state_after.to_dict()
        episode_result["life_transition"] = life_transition.to_dict()
        episode_result["neural_symbiosis_trace"] = symbiosis_trace
        if "experience" in episode_result:
            episode_result["experience"]["neural_symbiosis"] = {
                "trace_group_id": symbiosis_identity.trace_group_id,
                "organs": [
                    entry.get("organ") for entry in symbiosis_trace.get("organs", [])
                ],
                "n4_consumer_verdict": next(
                    (
                        entry.get("consumer_verdict")
                        for entry in symbiosis_trace.get("organs", [])
                        if entry.get("organ") == "N4"
                    ),
                    None,
                ),
            }

        # 14. EML shadow (opcional)
        eml_shadow = {"enabled": False, "status": "disabled"}
        if self.eml_mode == "shadow":
            dataset = self._build_eml_dataset(
                observation=observation_dict,
                factual=self.scenario.to_transition_dict(factual),
                counterfactual=self.scenario.to_transition_dict(counterfactual),
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
            "certification": dict(cert_summary),
            "eml_shadow": eml_shadow,
        }
