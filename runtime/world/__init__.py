"""Subsistema de mundo del runtime."""
"""Modelos de mundo del runtime RNFE."""

from .cgwm_min import CGWMMin, WorldState
from .min_cognitive_episode import MinimalCognitiveEpisodeRunner
from .compatibility import (
    CompatibilityAssessment,
    CompatibilityClass,
    ControlTopology,
    OptimizationDirection,
    ScenarioCompatibilityGraph,
    ScenarioStructuralProfile,
)
from .causal_signature import (
    CausalEdge,
    InterventionEffect,
    ScenarioCausalSignature,
)
from .causal_attestation import build_causal_attestation
from .alignment import (
    AlignmentPair,
    AlignmentResult,
    align_causal_graphs,
    align_interventions,
    align_propositions,
)
from .morphism_engine import (
    DirectedScenarioMorphism,
    MorphismClass,
    MorphismEngine,
    TransportOperator,
)
from .scenario import (
    CognitiveScenario,
    ScenarioConfig,
    ScenarioObservation,
    ScenarioTransition,
)
from .thermal_scenario import ThermalScenario, create_thermal_scenario
from .resource_scenario import ResourceScenario, create_resource_scenario
from .registry import (
    SCENARIO_REGISTRY,
    DEFAULT_SCENARIO,
    get_scenario,
    list_scenarios,
    list_structural_profiles,
    list_causal_signatures,
    register_scenario,
)
from .scenario_runner import ScenarioEpisodeRunner

__all__ = [
    # Legacy
    "CGWMMin",
    "WorldState",
    "MinimalCognitiveEpisodeRunner",
    # Compatibility graph
    "CompatibilityAssessment",
    "CompatibilityClass",
    "ControlTopology",
    "OptimizationDirection",
    "ScenarioCompatibilityGraph",
    "ScenarioStructuralProfile",
    # Causal signatures
    "CausalEdge",
    "InterventionEffect",
    "ScenarioCausalSignature",
    "build_causal_attestation",
    # Alignment
    "AlignmentPair",
    "AlignmentResult",
    "align_causal_graphs",
    "align_interventions",
    "align_propositions",
    # Morphism engine
    "DirectedScenarioMorphism",
    "MorphismClass",
    "MorphismEngine",
    "TransportOperator",
    # Scenario interface
    "CognitiveScenario",
    "ScenarioConfig",
    "ScenarioObservation",
    "ScenarioTransition",
    # Scenarios
    "ThermalScenario",
    "ResourceScenario",
    "create_thermal_scenario",
    "create_resource_scenario",
    # Registry
    "SCENARIO_REGISTRY",
    "DEFAULT_SCENARIO",
    "get_scenario",
    "list_scenarios",
    "list_structural_profiles",
    "list_causal_signatures",
    "register_scenario",
    # Runner
    "ScenarioEpisodeRunner",
]
