"""Registro de escenarios cognitivos disponibles."""

from __future__ import annotations

from typing import Dict, Type

from .compatibility import ScenarioStructuralProfile
from .causal_signature import ScenarioCausalSignature
from .scenario import CognitiveScenario, ScenarioConfig
from .thermal_scenario import ThermalScenario
from .resource_scenario import ResourceScenario
from .grid_thermal_scenario import GridThermalScenario
from .deferred_load_scenario import DeferredLoadScenario


# Registro de escenarios disponibles
SCENARIO_REGISTRY: Dict[str, Type[CognitiveScenario]] = {
    "thermal_homeostasis": ThermalScenario,
    "resource_management": ResourceScenario,
    "grid_thermal_5x5": GridThermalScenario,
    "deferred_load_trap": DeferredLoadScenario,
}

# Alias no canónicos (compatibilidad externa)
SCENARIO_ALIASES: Dict[str, str] = {
    "thermal": "thermal_homeostasis",
}

# Escenario por defecto (baseline)
DEFAULT_SCENARIO = "thermal_homeostasis"


def get_scenario(name: str, **kwargs) -> CognitiveScenario:
    """Obtiene instancia de escenario por nombre.

    Args:
        name: Nombre del escenario registrado.
        **kwargs: Parámetros de configuración del escenario.

    Returns:
        Instancia del escenario.

    Raises:
        ValueError: Si el escenario no existe.
    """
    canonical_name = SCENARIO_ALIASES.get(name, name)
    if canonical_name not in SCENARIO_REGISTRY:
        available = ", ".join(SCENARIO_REGISTRY.keys())
        raise ValueError(f"Escenario '{name}' no encontrado. Disponibles: {available}")

    scenario_class = SCENARIO_REGISTRY[canonical_name]
    return scenario_class(**kwargs)


def list_scenarios() -> Dict[str, ScenarioConfig]:
    """Lista configuraciones de todos los escenarios registrados.

    Returns:
        Dict con nombre -> configuración de cada escenario.
    """
    configs = {}
    for name, scenario_class in SCENARIO_REGISTRY.items():
        instance = scenario_class()
        configs[name] = instance.config
    return configs


def list_structural_profiles() -> Dict[str, ScenarioStructuralProfile]:
    """Lista perfiles estructurales de todos los escenarios registrados.

    Returns:
        Dict con nombre -> ScenarioStructuralProfile de cada escenario.
    """
    profiles = {}
    for name, scenario_class in SCENARIO_REGISTRY.items():
        instance = scenario_class()
        profiles[name] = instance.structural_profile
    return profiles


def register_scenario(name: str, scenario_class: Type[CognitiveScenario]) -> None:
    """Registra un nuevo escenario.

    Args:
        name: Nombre único del escenario.
        scenario_class: Clase del escenario (debe heredar de CognitiveScenario).
    """
    SCENARIO_REGISTRY[name] = scenario_class


def list_causal_signatures() -> Dict[str, ScenarioCausalSignature]:
    """Lista firmas causales de todos los escenarios registrados.

    Returns:
        Dict con nombre -> ScenarioCausalSignature de cada escenario.
    """
    signatures = {}
    for name, scenario_class in SCENARIO_REGISTRY.items():
        instance = scenario_class()
        signatures[name] = instance.causal_signature
    return signatures
