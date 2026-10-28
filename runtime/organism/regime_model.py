"""Modelo de régimen latente.

Un escenario observable es una realización concreta de un régimen latente.
La comparabilidad deja de ser nombre igual / nombre distinto y pasa a ser:
  - mismo régimen
  - régimen compatible
  - régimen transformable
  - régimen no transportable

Cada RegimeModel captura la estructura invariante que subyace a uno
o más escenarios concretos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Literal, Tuple


# ── Data contracts ───────────────────────────────────────────────────────────

RegimeCompatibility = Literal[
    "same_regime",
    "compatible_regime",
    "transformable_regime",
    "non_transportable",
]


@dataclass(frozen=True)
class RegimeModel:
    """Modelo de régimen latente bajo uno o más escenarios.

    Attributes:
        regime_id: Identificador único del régimen.
        control_topology: Topología de control ('single_loop', 'cascade', 'distributed').
        optimization_geometry: Geometría de optimización ('minimize', 'maximize', 'target_band').
        intervention_algebra: Álgebra de intervenciones ('additive', 'multiplicative', 'switching').
        counterfactual_law: Ley contrafactual ('perturbation', 'withholding', 'substitution').
        causal_polarity: Polaridad causal principal.
        response_sensitivity: Sensibilidad de respuesta [0, 1].
        equilibrium_class: Clase de equilibrio ('stable', 'unstable', 'metastable', 'oscillatory').
        recovery_profile: Perfil de recuperación ('fast', 'moderate', 'slow', 'non_recovering').
        scenario_instances: Escenarios concretos que realizan este régimen.
    """

    regime_id: str
    control_topology: Literal["single_loop", "cascade", "distributed"] = "single_loop"
    optimization_geometry: Literal["minimize", "maximize", "target_band"] = "minimize"
    intervention_algebra: Literal["additive", "multiplicative", "switching"] = "additive"
    counterfactual_law: Literal["perturbation", "withholding", "substitution"] = "perturbation"
    causal_polarity: Literal["lower_is_better", "higher_is_better", "contextual"] = "lower_is_better"
    response_sensitivity: float = 0.5
    equilibrium_class: Literal["stable", "unstable", "metastable", "oscillatory"] = "stable"
    recovery_profile: Literal["fast", "moderate", "slow", "non_recovering"] = "moderate"
    scenario_instances: FrozenSet[str] = frozenset()
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Regime comparison ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegimeComparisonResult:
    """Resultado de comparación entre dos regímenes."""

    source_regime: str
    target_regime: str
    compatibility: RegimeCompatibility
    structural_distance: float    # [0, 1]
    topology_match: bool
    geometry_match: bool
    algebra_match: bool
    law_match: bool
    polarity_match: bool
    equilibrium_match: bool
    transport_feasibility: float  # [0, 1]


def compare_regimes(
    source: RegimeModel,
    target: RegimeModel,
) -> RegimeComparisonResult:
    """Compara dos regímenes y determina compatibilidad.

    Args:
        source: Régimen fuente.
        target: Régimen destino.

    Returns:
        RegimeComparisonResult con compatibilidad y distancia.
    """
    topo = source.control_topology == target.control_topology
    geom = source.optimization_geometry == target.optimization_geometry
    alg = source.intervention_algebra == target.intervention_algebra
    law = source.counterfactual_law == target.counterfactual_law
    pol = source.causal_polarity == target.causal_polarity
    eq = source.equilibrium_class == target.equilibrium_class

    matches = [topo, geom, alg, law, pol, eq]
    match_count = sum(matches)
    total = len(matches)

    # Structural distance
    distance = 1.0 - (match_count / total)

    # Sensitivity distance
    sens_diff = abs(source.response_sensitivity - target.response_sensitivity)
    distance = 0.7 * distance + 0.3 * sens_diff

    # Recovery compatibility
    recovery_map = {"fast": 0, "moderate": 1, "slow": 2, "non_recovering": 3}
    recovery_diff = abs(
        recovery_map.get(source.recovery_profile, 1)
        - recovery_map.get(target.recovery_profile, 1)
    ) / 3.0

    # Transport feasibility
    feasibility = max(0.0, 1.0 - distance - 0.2 * recovery_diff)

    # Compatibility classification
    if source.regime_id == target.regime_id:
        compat = "same_regime"
    elif match_count >= 5:
        compat = "compatible_regime"
    elif match_count >= 3 and feasibility > 0.3:
        compat = "transformable_regime"
    else:
        compat = "non_transportable"

    return RegimeComparisonResult(
        source_regime=source.regime_id,
        target_regime=target.regime_id,
        compatibility=compat,
        structural_distance=round(distance, 4),
        topology_match=topo,
        geometry_match=geom,
        algebra_match=alg,
        law_match=law,
        polarity_match=pol,
        equilibrium_match=eq,
        transport_feasibility=round(feasibility, 4),
    )


# ── Built-in regime models ───────────────────────────────────────────────────

THERMAL_REGIME = RegimeModel(
    regime_id="homeostatic_cooling",
    control_topology="single_loop",
    optimization_geometry="minimize",
    intervention_algebra="additive",
    counterfactual_law="perturbation",
    causal_polarity="lower_is_better",
    response_sensitivity=0.6,
    equilibrium_class="stable",
    recovery_profile="fast",
    scenario_instances=frozenset({"thermal_homeostasis"}),
)

RESOURCE_REGIME = RegimeModel(
    regime_id="inventory_maximization",
    control_topology="single_loop",
    optimization_geometry="maximize",
    intervention_algebra="additive",
    counterfactual_law="perturbation",
    causal_polarity="higher_is_better",
    response_sensitivity=0.5,
    equilibrium_class="stable",
    recovery_profile="moderate",
    scenario_instances=frozenset({"resource_management"}),
)

# ── B26.1 — regímenes de los escenarios extra-canon ──────────────────────────
# Criterio: canon/normative/SCENARIO_CONTRACTS_v1.md §6.3 y §6.4 (re-emisión A17),
# cruzado con el SSOT vivo de cada escenario (`structural_profile` y
# `causal_signature`, que el canon declara literales del registry).
#
# Cada campo lleva su fuente. Donde el canon NO determina el valor, se dice.

GRID_THERMAL_REGIME = RegimeModel(
    regime_id="spatial_homeostatic_cooling",
    # canon §6.3: topología `threshold_single_loop_spatial`, "control sobre estado
    # distribuido". NO es `threshold_single_loop`: el estado son 25 celdas y la
    # política lee estructura espacial (hotspots, gradiente, concentración).
    # El enum de RegimeModel no tiene una casilla nativa para "single_loop espacial";
    # `distributed` es la que preserva la distinción con thermal (ver metadata).
    control_topology="distributed",
    optimization_geometry="minimize",          # canon §6.3
    intervention_algebra="additive",           # código: temp + heat - cooling_delta
    counterfactual_law="perturbation",         # canon §6.3: opposite_intervention
    causal_polarity="lower_is_better",         # canon §6.3
    # Mismo `cooling_effect` (0.07) y misma ley de control que thermal: la
    # sensibilidad se HEREDA del régimen que extiende, no se inventa.
    response_sensitivity=0.6,
    equilibrium_class="stable",                # mismo atractor homeostático; sin estado oculto
    recovery_profile="fast",                   # mismo cooling_effect que thermal
    scenario_instances=frozenset({"grid_thermal_5x5"}),
    metadata={
        "canon_ref": "SCENARIO_CONTRACTS_v1.md#6.3",
        "canon_status": "extra_canon_provisional",
        "canonical_control_topology": "threshold_single_loop_spatial",
        "topology_note": (
            "El enum RegimeModel.control_topology (single_loop|cascade|distributed) no "
            "representa 'single_loop espacial'. Se elige `distributed` porque el estado "
            "controlado es distribuido (canon §6.3); la topología canónica exacta queda "
            "registrada acá para no perderla."
        ),
    },
)

DEFERRED_LOAD_REGIME = RegimeModel(
    regime_id="deferred_debt_homeostasis",
    control_topology="single_loop",            # canon §6.4: `threshold_single_loop`
    optimization_geometry="minimize",          # canon §6.4
    intervention_algebra="additive",           # código: load + external + load_delta + debt
    counterfactual_law="perturbation",         # canon §6.4: opposite_intervention
    causal_polarity="lower_is_better",         # canon §6.4
    # NO DETERMINADO POR EL CANON. El canon no da semántica de `response_sensitivity`,
    # y los dos regímenes canónicos no exhiben ninguna fórmula derivable (thermal:
    # efecto 0.07 -> 0.6; resource: efecto 0.08 -> 0.5, es decir NO monótona en la
    # magnitud del efecto). Se usa el default neutro del dataclass (0.5) en vez de
    # fabricar un número con aire de medición. Declarado en metadata.
    response_sensitivity=0.5,
    # SÍ determinados, y son lo que define a este régimen:
    # la deuda diferida rebota la carga hacia la alarma (canon §6.4: "rebota vía
    # deuda diferida") => el equilibrio APARENTA ser estable y no lo es.
    equilibrium_class="metastable",
    # boost_debt=0.08 inyecta deuda 4x más rápido de lo que shed_debt=0.02 la drena.
    recovery_profile="slow",
    scenario_instances=frozenset({"deferred_load_trap"}),
    metadata={
        "canon_ref": "SCENARIO_CONTRACTS_v1.md#6.4",
        "canon_status": "extra_canon_provisional",
        "canonical_control_topology": "threshold_single_loop_with_deferred_consequence",
        "response_sensitivity_basis": "canon_undetermined_neutral_default",
        "trap_note": (
            "La magnitud inmediata de `boost_throughput` (0.15) supera a la de "
            "`shed_load` (0.05), pero es la trampa: inyecta deuda que rebota. La "
            "sensibilidad inmediata SOBRESTIMA la respuesta sostenida; por eso no se "
            "la usa como `response_sensitivity`."
        ),
    },
)

# Registry
REGIME_REGISTRY: Dict[str, RegimeModel] = {
    "homeostatic_cooling": THERMAL_REGIME,
    "inventory_maximization": RESOURCE_REGIME,
    "spatial_homeostatic_cooling": GRID_THERMAL_REGIME,
    "deferred_debt_homeostasis": DEFERRED_LOAD_REGIME,
}

# B26.1: los 4 escenarios de `runtime/world/registry.py::SCENARIO_REGISTRY` tienen
# régimen. Un escenario NUEVO sin régimen sigue siendo posible — y por eso B26.2
# hace EXPLÍCITA la omisión en vez de puntuarla como renormalización perfecta.
SCENARIO_TO_REGIME: Dict[str, str] = {
    "thermal_homeostasis": "homeostatic_cooling",
    "resource_management": "inventory_maximization",
    "grid_thermal_5x5": "spatial_homeostatic_cooling",
    "deferred_load_trap": "deferred_debt_homeostasis",
}


def get_regime_for_scenario(scenario_name: str) -> RegimeModel | None:
    """Obtiene el régimen latente para un escenario.

    Devuelve ``None`` si el escenario no tiene régimen mapeado. ``None`` significa
    NO SÉ RENORMALIZAR ESTO — no significa "renormalización trivial". Quien lo
    consuma debe tratarlo como AUSENCIA DE EVIDENCIA (ver B26.2: court_runtime,
    failure_atlas y risk_process se abstienen ante un cruce no mapeado).
    """
    regime_id = SCENARIO_TO_REGIME.get(scenario_name)
    if regime_id is None:
        return None
    return REGIME_REGISTRY.get(regime_id)


def is_scenario_mapped(scenario_name: str) -> bool:
    """True si el escenario tiene un régimen latente conocido."""
    return get_regime_for_scenario(scenario_name) is not None
