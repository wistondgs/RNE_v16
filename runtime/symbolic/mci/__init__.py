"""Módulo de Cognición Integrada."""

from .compiler import TransitionCompiler
from .causal_learning import CausalLearningEngine, TransitionEvidence
from .contracts import (
    BeliefNode,
    CausalOverlay,
    MCICommitReport,
    SMTPlanReport,
    SelfModelReport,
    TransitionSpec,
    Justification,
    NeuralHypothesis,
    NeuralHypothesisEvaluation,
)
from .jtms import TemporalAssumptionLedger
from .planner import MCIPlanningConfig, SMTPlanner
from .runtime import MCIRuntime
from .hypothesis_mapping import (
    EdgeMapping,
    HypothesisMappingRegistry,
    default_edge_mappings,
)
from .provider_protocol import ExternalHypothesis, HypothesisProvider
from .regime_detector import RegimeChangeDetected, RegimeDetector
from .self_model import IncrementalSelfModel
from .specs import (
    deferred_load_spec,
    resource_spec,
    thermal_battery_spec,
    thermal_spec,
)

__all__ = [
    "BeliefNode",
    "CausalOverlay",
    "CausalLearningEngine",
    "IncrementalSelfModel",
    "Justification",
    "NeuralHypothesis",
    "NeuralHypothesisEvaluation",
    "MCICommitReport",
    "MCIPlanningConfig",
    "MCIRuntime",
    "EdgeMapping",
    "ExternalHypothesis",
    "HypothesisMappingRegistry",
    "default_edge_mappings",
    "HypothesisProvider",
    "RegimeChangeDetected",
    "RegimeDetector",
    "SMTPlanReport",
    "SelfModelReport",
    "SMTPlanner",
    "TemporalAssumptionLedger",
    "TransitionEvidence",
    "TransitionCompiler",
    "TransitionSpec",
    "deferred_load_spec",
    "resource_spec",
    "thermal_spec",
    "thermal_battery_spec",
]
