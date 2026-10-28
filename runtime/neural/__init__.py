"""Sistema nervioso N0 de RNFE (sin dependencias neuronales eager)."""

from .config import NeuralRuntimeConfig
from .benchmark import ImpactObservation, build_impact_report, expected_calibration_error
from .contracts import (
    AdmissionDecision,
    BackendOutput,
    CausalContextView,
    CausalLinkage,
    DecisionInfluence,
    DevicePreference,
    InferenceScope,
    NeuralBackend,
    NeuralInferenceRequest,
    NeuralInferenceResult,
    NeuralMode,
    NeuralModelManifest,
    OrganAdapter,
    OrganismImpactReport,
    OrganismImpactVector,
    ResourceSnapshot,
)
from .registry import BackendRegistryError, LazyBackendRegistry
from .runtime import NeuralRuntime
from .observability import TraceHealthSnapshot, TracePersistenceMonitor

__all__ = [
    "AdmissionDecision",
    "BackendOutput",
    "BackendRegistryError",
    "CausalContextView",
    "CausalLinkage",
    "DecisionInfluence",
    "DevicePreference",
    "InferenceScope",
    "ImpactObservation",
    "LazyBackendRegistry",
    "NeuralBackend",
    "NeuralInferenceRequest",
    "NeuralInferenceResult",
    "NeuralMode",
    "NeuralModelManifest",
    "NeuralRuntime",
    "NeuralRuntimeConfig",
    "OrganAdapter",
    "OrganismImpactReport",
    "OrganismImpactVector",
    "ResourceSnapshot",
    "TraceHealthSnapshot",
    "TracePersistenceMonitor",
    "build_impact_report",
    "expected_calibration_error",
]
