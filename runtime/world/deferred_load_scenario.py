"""Escenario de consecuencia diferida — trampa temporal para foresight (A11).

Homeostasis de carga (`load`, menor = mejor) con una **trampa temporal**:

- `boost_throughput`: baja mucho la carga en el paso actual (Δ lineal grande) — el
  núcleo reactivo/1-paso lo ve como el mejor arreglo — pero acumula una deuda oculta
  (`debt`) que **rebota** la carga hacia la alarma en pocos pasos.
- `shed_load`: baja poco ahora, pero es sostenible (reduce deuda).

Diseño: el effect-model lineal (core_inference._effect_model) sólo lee la magnitud
inmediata de `intervention_effects`, así que ve `boost_throughput` como la
intervención más correctiva y cae en la trampa. Sólo un lector multi-paso del estado
(la imaginación A11) ve que la deuda rebota y elige `shed_load`. Es el terreno donde
la previsión paga y donde A11 puede ganarle a `core_only` de forma medible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .compatibility import ScenarioStructuralProfile
from .causal_signature import (
    CausalEdge,
    InterventionEffect,
    ScenarioCausalSignature,
)
from .scenario import (
    CognitiveScenario,
    ScenarioConfig,
    ScenarioObservation,
    ScenarioTransition,
)


@dataclass
class DeferredLoadState:
    """Estado interno del mundo de carga diferida."""

    load: float
    debt: float
    boosting: bool
    alarm: bool


class DeferredLoadScenario(CognitiveScenario):
    """Homeostasis de carga con consecuencia diferida (trampa temporal).

    - Variable principal: `load` (0.0-1.0), menor es mejor.
    - Intervenciones: `boost_throughput` (trampa), `shed_load` (previsor).
    - Umbral de alarma: configurable (default 0.85).
    - Dinámica: la deuda acumulada empuja la carga hacia arriba cada paso; `boost`
      inyecta deuda, `shed` la reduce.
    """

    def __init__(
        self,
        *,
        initial_load: float = 0.70,
        alarm_threshold: float = 0.85,
        boost_effect: float = 0.15,
        shed_effect: float = 0.05,
        boost_debt: float = 0.08,
        shed_debt: float = 0.02,
    ):
        self._alarm_threshold = alarm_threshold
        self._boost_effect = boost_effect
        self._shed_effect = shed_effect
        self._boost_debt = boost_debt
        self._shed_debt = shed_debt
        self._state = DeferredLoadState(
            load=initial_load,
            debt=0.0,
            boosting=False,
            alarm=initial_load >= alarm_threshold,
        )
        self._config = ScenarioConfig(
            name="deferred_load_trap",
            description="Homeostasis de carga con consecuencia diferida (boost rebota vía deuda)",
            main_variable="load",
            alarm_threshold=alarm_threshold,
            interventions=["boost_throughput", "shed_load"],
            formula_template="LOAD_HIGH -> SHED_LOAD",
            type_context={"LOAD_HIGH": "bool", "SHED_LOAD": "bool"},
        )

    @property
    def config(self) -> ScenarioConfig:
        return self._config

    @property
    def structural_profile(self) -> ScenarioStructuralProfile:
        cfg = self._config
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
        return ScenarioStructuralProfile(
            scenario_name=cfg.name,
            scenario_version="1.0",
            scenario_config_hash=config_hash,
            control_topology="threshold_single_loop",
            optimization_direction="minimize",
            intervention_semantics=tuple(cfg.interventions),
            counterfactual_policy="opposite_intervention",
            relation_polarity="lower_is_better",
            main_variable=cfg.main_variable,
        )

    @property
    def causal_signature(self) -> ScenarioCausalSignature:
        cfg = self._config
        return ScenarioCausalSignature(
            scenario_name=cfg.name,
            scenario_version="1.0",
            observable_variables=frozenset({"load", "debt", "boosting"}),
            control_variables=frozenset({"boosting"}),
            main_variable="load",
            optimization_direction="minimize",
            causal_polarity="lower_is_better",
            alarm_semantics="threshold_above",
            intervention_effects=(
                # OJO: boost tiene la mayor magnitud inmediata ⇒ el effect-model lineal
                # lo prefiere. La consecuencia diferida (deuda) NO está en la magnitud.
                InterventionEffect(
                    intervention_name="boost_throughput",
                    target_variable="load",
                    expected_direction="-",
                    expected_magnitude=self._boost_effect,
                    semantic_role="corrective",
                ),
                InterventionEffect(
                    intervention_name="shed_load",
                    target_variable="load",
                    expected_direction="-",
                    expected_magnitude=self._shed_effect,
                    semantic_role="corrective",
                ),
            ),
            counterfactual_policy="opposite_intervention",
            counterfactual_variable="load",
            causal_edges=(
                CausalEdge(source="external_input", target="load", polarity="+"),
                CausalEdge(source="debt", target="load", polarity="+"),
                CausalEdge(source="boost_throughput", target="debt", polarity="+"),
                CausalEdge(source="shed_load", target="debt", polarity="-"),
                CausalEdge(source="load", target="alarm", polarity="+"),
            ),
            proposition_vocabulary=frozenset({
                "LOAD_HIGH", "LOAD_NORMAL", "BOOSTING", "SHED_LOAD", "BOOST_THROUGHPUT",
            }),
        )

    @property
    def alarm_threshold(self) -> float:
        return self._alarm_threshold

    def observe(self) -> ScenarioObservation:
        load_high = self._state.load >= self._alarm_threshold
        propositions = ["LOAD_HIGH"] if load_high else ["LOAD_NORMAL"]
        if self._state.boosting:
            propositions.append("BOOSTING")
        return ScenarioObservation(
            state={
                "load": self._state.load,
                "debt": self._state.debt,
                "boosting": self._state.boosting,
            },
            propositions=propositions,
            alarm=self._state.alarm,
        )

    def _compute_transition(
        self,
        state: DeferredLoadState,
        *,
        intervention: str,
        external_input: float,
    ) -> DeferredLoadState:
        boosting = state.boosting
        load_delta = 0.0
        debt_delta = 0.0
        if intervention == "boost_throughput":
            boosting = True
            load_delta = -self._boost_effect
            debt_delta = +self._boost_debt
        elif intervention == "shed_load":
            boosting = False
            load_delta = -self._shed_effect
            debt_delta = -self._shed_debt

        next_debt = max(0.0, min(1.0, state.debt + debt_delta))
        # La deuda acumulada empuja la carga hacia arriba: consecuencia diferida.
        next_load = max(0.0, min(1.0, state.load + external_input + load_delta + next_debt))
        return DeferredLoadState(
            load=next_load,
            debt=next_debt,
            boosting=boosting,
            alarm=next_load >= self._alarm_threshold,
        )

    def factual_transition(
        self,
        *,
        intervention: str,
        external_input: float,
    ) -> ScenarioTransition:
        self._state = self._compute_transition(
            self._state, intervention=intervention, external_input=external_input
        )
        return ScenarioTransition(
            state={
                "load": self._state.load,
                "debt": self._state.debt,
                "boosting": self._state.boosting,
            },
            propositions=self.observe().propositions,
            alarm=self._state.alarm,
        )

    def simulate_counterfactual(
        self,
        *,
        intervention: str,
        external_input: float,
    ) -> ScenarioTransition:
        simulated = self._compute_transition(
            self._state, intervention=intervention, external_input=external_input
        )
        return ScenarioTransition(
            state={
                "load": simulated.load,
                "debt": simulated.debt,
                "boosting": simulated.boosting,
            },
            propositions=[
                "LOAD_HIGH" if simulated.load >= self._alarm_threshold else "LOAD_NORMAL"
            ],
            alarm=simulated.alarm,
        )

    def get_formula(self, observation: ScenarioObservation) -> str:
        return self._config.formula_template

    def select_intervention(self, observation: ScenarioObservation) -> str:
        # Política reactiva ingenua (víctima de la trampa): ante carga elevada elige el
        # arreglo inmediato más fuerte (boost, el de mayor Δ lineal) — que rebota vía
        # deuda. El organismo previsor debe aprender a preferir shed; lo hace vía el
        # override de previsión A11+A12 (bajo RNFE_REASONING_ACTUATES).
        if observation.state.get("load", 0.0) >= 0.6:
            return "boost_throughput"
        return "shed_load"

    def get_main_proposition(self, observation: ScenarioObservation) -> str:
        if observation.alarm:
            return "LOAD_HIGH"
        return "LOAD_NORMAL"

    def get_intervention_proposition(self, intervention: str) -> str:
        if intervention == "boost_throughput":
            return "BOOST_THROUGHPUT"
        return "SHED_LOAD"


def create_deferred_load_scenario(
    *,
    initial_load: float = 0.70,
    alarm_threshold: float = 0.85,
) -> DeferredLoadScenario:
    """Crea el escenario-trampa con configuración por defecto."""
    return DeferredLoadScenario(
        initial_load=initial_load,
        alarm_threshold=alarm_threshold,
    )
