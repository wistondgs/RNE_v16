"""Escenario de gestión de recursos/inventario - segundo escenario de referencia."""

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
class ResourceWorldState:
    """Estado interno del mundo de recursos."""

    stock_level: float  # 0.0 - 1.0 (porcentaje de capacidad)
    production_active: bool
    scarcity_alert: bool


class ResourceScenario(CognitiveScenario):
    """Escenario de gestión de recursos/inventario.

    Este escenario modela un sistema de control de inventario con:
    - Variable principal: stock_level (0.0 - 1.0)
    - Intervenciones: start_production, stop_production
    - Umbral de escasez: configurable (default 0.20)
    - Dinámica: producción aumenta stock, consumo lo reduce

    La causalidad es inversa al escenario térmico:
    - En térmico: HIGH -> ACTIVATE (reducir valor alto)
    - En recursos: LOW -> ACTIVATE (aumentar valor bajo)
    """

    def __init__(
        self,
        *,
        initial_stock: float = 0.25,
        scarcity_threshold: float = 0.20,
        production_rate: float = 0.08,
    ):
        """Inicializa escenario de recursos.

        Args:
            initial_stock: Nivel de stock inicial (0.0-1.0).
            scarcity_threshold: Umbral de escasez.
            production_rate: Tasa de producción por paso.
        """
        self._scarcity_threshold = scarcity_threshold
        self._production_rate = production_rate
        self._state = ResourceWorldState(
            stock_level=initial_stock,
            production_active=False,
            scarcity_alert=initial_stock <= scarcity_threshold,
        )
        self._config = ScenarioConfig(
            name="resource_management",
            description="Gestión de inventario con producción activable",
            main_variable="stock_level",
            alarm_threshold=scarcity_threshold,
            interventions=["start_production", "stop_production"],
            formula_template="STOCK_LOW -> START_PRODUCTION",
            type_context={"STOCK_LOW": "bool", "START_PRODUCTION": "bool"},
        )

    @property
    def config(self) -> ScenarioConfig:
        return self._config

    @property
    def structural_profile(self) -> ScenarioStructuralProfile:
        """Perfil estructural para evaluación de compatibilidad."""
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
            control_topology="threshold_recovery_loop",
            optimization_direction="maximize",
            intervention_semantics=tuple(cfg.interventions),
            counterfactual_policy="opposite_intervention",
            relation_polarity="higher_is_better",
            main_variable=cfg.main_variable,
        )

    @property
    def causal_signature(self) -> ScenarioCausalSignature:
        """Firma causal completa para morfismos dirigidos."""
        cfg = self._config
        return ScenarioCausalSignature(
            scenario_name=cfg.name,
            scenario_version="1.0",
            observable_variables=frozenset({"stock_level", "production_active"}),
            control_variables=frozenset({"production_active"}),
            main_variable="stock_level",
            optimization_direction="maximize",
            causal_polarity="higher_is_better",
            alarm_semantics="threshold_below",
            intervention_effects=(
                InterventionEffect(
                    intervention_name="start_production",
                    target_variable="stock_level",
                    expected_direction="+",
                    expected_magnitude=self._production_rate,
                    semantic_role="corrective",
                ),
                InterventionEffect(
                    intervention_name="stop_production",
                    target_variable="stock_level",
                    expected_direction="-",
                    expected_magnitude=0.0,
                    semantic_role="neutral",
                ),
            ),
            counterfactual_policy="opposite_intervention",
            counterfactual_variable="stock_level",
            causal_edges=(
                CausalEdge(source="external_consumption", target="stock_level", polarity="-"),
                CausalEdge(source="production_active", target="stock_level", polarity="+"),
                CausalEdge(source="stock_level", target="scarcity_alert", polarity="-"),
            ),
            proposition_vocabulary=frozenset({
                "STOCK_LOW", "STOCK_ADEQUATE", "PRODUCTION_ACTIVE",
                "START_PRODUCTION", "KEEP_IDLE",
            }),
        )

    @property
    def alarm_threshold(self) -> float:
        """Umbral de escasez para compatibilidad."""
        return self._scarcity_threshold

    def observe(self) -> ScenarioObservation:
        stock_low = self._state.stock_level <= self._scarcity_threshold
        propositions = ["STOCK_LOW"] if stock_low else ["STOCK_ADEQUATE"]
        if self._state.production_active:
            propositions.append("PRODUCTION_ACTIVE")

        return ScenarioObservation(
            state={
                "stock_level": self._state.stock_level,
                "production_active": self._state.production_active,
            },
            propositions=propositions,
            alarm=self._state.scarcity_alert,
        )

    def _compute_transition(
        self,
        state: ResourceWorldState,
        *,
        intervention: str,
        external_input: float,
    ) -> ResourceWorldState:
        """Computa transición de estado.

        Args:
            state: Estado actual.
            intervention: Intervención a aplicar.
            external_input: Consumo externo (reduce stock).
        """
        production_active = state.production_active
        if intervention == "start_production":
            production_active = True
        elif intervention == "stop_production":
            production_active = False

        production_delta = self._production_rate if production_active else 0.0
        # Consumo reduce, producción aumenta
        next_stock = max(0.0, min(1.0, state.stock_level - external_input + production_delta))

        return ResourceWorldState(
            stock_level=next_stock,
            production_active=production_active,
            scarcity_alert=next_stock <= self._scarcity_threshold,
        )

    def factual_transition(
        self,
        *,
        intervention: str,
        external_input: float,
    ) -> ScenarioTransition:
        self._state = self._compute_transition(
            self._state,
            intervention=intervention,
            external_input=external_input,
        )
        return ScenarioTransition(
            state={
                "stock_level": self._state.stock_level,
                "production_active": self._state.production_active,
            },
            propositions=self.observe().propositions,
            alarm=self._state.scarcity_alert,
        )

    def simulate_counterfactual(
        self,
        *,
        intervention: str,
        external_input: float,
    ) -> ScenarioTransition:
        simulated = self._compute_transition(
            self._state,
            intervention=intervention,
            external_input=external_input,
        )
        return ScenarioTransition(
            state={
                "stock_level": simulated.stock_level,
                "production_active": simulated.production_active,
            },
            propositions=[
                "STOCK_LOW"
                if simulated.stock_level <= self._scarcity_threshold
                else "STOCK_ADEQUATE"
            ],
            alarm=simulated.scarcity_alert,
        )

    def get_formula(self, observation: ScenarioObservation) -> str:
        return self._config.formula_template

    def select_intervention(self, observation: ScenarioObservation) -> str:
        # En recursos: activar producción cuando hay escasez
        if observation.alarm:
            return "start_production"
        return "stop_production"

    def get_main_proposition(self, observation: ScenarioObservation) -> str:
        if observation.alarm:
            return "STOCK_LOW"
        return "STOCK_ADEQUATE"

    def get_intervention_proposition(self, intervention: str) -> str:
        if intervention == "start_production":
            return "START_PRODUCTION"
        return "KEEP_IDLE"

    def evaluate_relation_kind(
        self,
        *,
        factual: ScenarioTransition,
        counterfactual: ScenarioTransition,
    ) -> str:
        """Evalúa relación - en recursos, más stock es mejor."""
        main_var = self.config.main_variable
        factual_val = factual.state.get(main_var, 0.0)
        counterfactual_val = counterfactual.state.get(main_var, 0.0)

        # Si factual tiene más o igual stock que contrafactual, es support
        if factual_val >= counterfactual_val:
            return "support"
        return "contradiction"


# Factory function
def create_resource_scenario(
    *,
    initial_stock: float = 0.25,
    scarcity_threshold: float = 0.20,
) -> ResourceScenario:
    """Crea escenario de recursos con configuración por defecto."""
    return ResourceScenario(
        initial_stock=initial_stock,
        scarcity_threshold=scarcity_threshold,
    )
