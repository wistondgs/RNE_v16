"""Contratos publicos del runtime neuronal RNFE.

El modulo es deliberadamente puro Python: importar ``runtime.neural`` nunca
debe cargar frameworks, pesos ni dispositivos.  Todos los modelos devuelven
propuestas; la autoridad sigue en los gates y certificadores del organismo.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol, runtime_checkable


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class NeuralMode(str, Enum):
    OFF = "off"
    EXPERIMENTAL = "experimental"
    SHADOW = "shadow"
    PROVISIONAL = "provisional"


class InferenceScope(str, Enum):
    LAB = "lab"
    LIVE = "live"


class DevicePreference(str, Enum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"


class CausalLinkage(str, Enum):
    UNLINKED = "unlinked"
    DECISION_LINKED = "decision_linked"
    COMPLETE = "complete"


class DecisionInfluence(str, Enum):
    NONE = "none"
    BOUNDED_PROPOSAL = "bounded_proposal"


def _json_value(value: Any) -> Any:
    """Devuelve una copia JSON-safe o falla de forma explicita."""

    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ValueError("value_must_be_json_serializable") from exc


@dataclass(frozen=True, slots=True)
class NeuralModelManifest:
    organ: str
    capability: str
    model_id: str
    version: str
    backend: str
    artifact_path: str
    artifact_sha256: str
    input_schema_version: str
    output_schema_version: str
    supported_devices: tuple[str, ...]
    supported_dtypes: tuple[str, ...] = ("float32",)
    parameter_count: int = 0
    peak_vram_gb: float = 0.0
    license_id: str = ""
    upstream_url: str = ""
    upstream_commit: str = ""
    training_provenance: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        organ = self.organ.strip().upper()
        if organ not in {f"N{index}" for index in range(1, 7)}:
            raise ValueError(f"unsupported_neural_organ:{self.organ}")
        object.__setattr__(self, "organ", organ)
        for name in ("capability", "model_id", "version", "backend"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"manifest_field_required:{name}")
        relative = PurePosixPath(self.artifact_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("artifact_path_must_be_safe_relative_path")
        if not _SHA256_RE.fullmatch(self.artifact_sha256):
            raise ValueError("artifact_sha256_must_be_lowercase_sha256")
        devices = tuple(dict.fromkeys(item.strip().lower() for item in self.supported_devices))
        if not devices or any(item not in {"cpu", "cuda"} for item in devices):
            raise ValueError("supported_devices_must_be_cpu_or_cuda")
        object.__setattr__(self, "supported_devices", devices)
        if not self.input_schema_version or not self.output_schema_version:
            raise ValueError("schema_versions_are_required")
        if self.parameter_count < 0 or self.peak_vram_gb < 0.0:
            raise ValueError("model_resource_values_must_be_non_negative")
        if not self.license_id.strip():
            raise ValueError("license_id_is_required")
        if not self.upstream_url.strip() or not self.upstream_commit.strip():
            raise ValueError("upstream_url_and_commit_are_required")
        if not self.training_provenance:
            raise ValueError("training_provenance_is_required")
        object.__setattr__(self, "training_provenance", _json_value(self.training_provenance))
        object.__setattr__(self, "metrics", _json_value(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "organ": self.organ,
            "capability": self.capability,
            "model_id": self.model_id,
            "version": self.version,
            "backend": self.backend,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "supported_devices": list(self.supported_devices),
            "supported_dtypes": list(self.supported_dtypes),
            "parameter_count": self.parameter_count,
            "peak_vram_gb": self.peak_vram_gb,
            "license_id": self.license_id,
            "upstream_url": self.upstream_url,
            "upstream_commit": self.upstream_commit,
            "training_provenance": _json_value(self.training_provenance),
            "metrics": _json_value(self.metrics),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NeuralModelManifest":
        payload = dict(raw)
        payload["supported_devices"] = tuple(payload.get("supported_devices", ()))
        payload["supported_dtypes"] = tuple(payload.get("supported_dtypes", ("float32",)))
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class CausalContextView:
    organism_id: str | None = None
    decision_id: str | None = None
    episode_id: str | None = None
    trace_id: str | None = None
    certificate_id: str | None = None

    @property
    def linkage(self) -> CausalLinkage:
        values = (
            self.organism_id,
            self.decision_id,
            self.episode_id,
            self.trace_id,
            self.certificate_id,
        )
        if all(values):
            return CausalLinkage.COMPLETE
        if self.organism_id and self.decision_id:
            return CausalLinkage.DECISION_LINKED
        return CausalLinkage.UNLINKED

    @property
    def permits_decision_influence(self) -> bool:
        return self.linkage in {CausalLinkage.DECISION_LINKED, CausalLinkage.COMPLETE}

    def to_dict(self) -> dict[str, str | None]:
        return {
            "organism_id": self.organism_id,
            "decision_id": self.decision_id,
            "episode_id": self.episode_id,
            "trace_id": self.trace_id,
            "certificate_id": self.certificate_id,
        }


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    cpu_pressure: float = 0.0
    memory_pressure: float = 0.0
    thermal_pressure: float = 0.0
    gpu_available: bool = False
    vram_pressure: float = 1.0
    vram_used_gb: float | None = None
    vram_total_gb: float | None = None
    gpu_temperature_c: float | None = None
    msrc_budget_available: bool = True
    msrc_scale_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("cpu_pressure", "memory_pressure", "thermal_pressure", "vram_pressure"):
            value = min(max(float(getattr(self, name)), 0.0), 1.0)
            object.__setattr__(self, name, value)
        for name in ("vram_used_gb", "vram_total_gb", "gpu_temperature_c"):
            value = getattr(self, name)
            if value is not None and float(value) < 0.0:
                raise ValueError(f"resource_value_must_be_non_negative:{name}")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ResourceSnapshot":
        data = dict(raw or {})
        return cls(
            cpu_pressure=float(data.get("cpu_pressure", 0.0) or 0.0),
            memory_pressure=float(data.get("memory_pressure", 0.0) or 0.0),
            thermal_pressure=float(data.get("thermal_pressure", 0.0) or 0.0),
            gpu_available=bool(data.get("gpu_available", data.get("available", False))),
            vram_pressure=float(data.get("vram_pressure", 1.0) or 0.0),
            vram_used_gb=_optional_float(data.get("vram_used_gb", data.get("used_gb"))),
            vram_total_gb=_optional_float(data.get("vram_total_gb", data.get("total_gb"))),
            gpu_temperature_c=_optional_float(
                data.get("gpu_temperature_c", data.get("temperature_c"))
            ),
            msrc_budget_available=bool(data.get("msrc_budget_available", True)),
            msrc_scale_id=(
                str(data["msrc_scale_id"])
                if data.get("msrc_scale_id") is not None
                else None
            ),
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class NeuralInferenceRequest:
    inference_id: str
    run_id: str
    organ: str
    capability: str
    payload: Mapping[str, Any]
    seed: int = 0
    scope: InferenceScope = InferenceScope.LIVE
    resources: ResourceSnapshot = field(default_factory=ResourceSnapshot)
    causal_context: CausalContextView | None = None

    def __post_init__(self) -> None:
        if not self.inference_id or not self.run_id:
            raise ValueError("inference_id_and_run_id_are_required")
        object.__setattr__(self, "organ", self.organ.strip().upper())
        object.__setattr__(self, "payload", _json_value(self.payload))

    @property
    def causal_linkage(self) -> CausalLinkage:
        if self.causal_context is None:
            return CausalLinkage.UNLINKED
        return self.causal_context.linkage


@dataclass(frozen=True, slots=True)
class BackendOutput:
    candidate_output: Any
    confidence: float = 0.0
    uncertainty: float = 1.0
    cost: Mapping[str, Any] = field(default_factory=dict)
    trace: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_output", _json_value(self.candidate_output))
        object.__setattr__(self, "confidence", min(max(float(self.confidence), 0.0), 1.0))
        object.__setattr__(self, "uncertainty", min(max(float(self.uncertainty), 0.0), 1.0))
        object.__setattr__(self, "cost", _json_value(self.cost))
        object.__setattr__(self, "trace", tuple(_json_value(item) for item in self.trace))


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    accepted: bool
    output: Any = None
    reason: str = ""
    effective_mode_ceiling: NeuralMode | None = None

    def __post_init__(self) -> None:
        if self.accepted and not self.reason:
            object.__setattr__(self, "reason", "admitted")
        if self.effective_mode_ceiling is not None and not isinstance(
            self.effective_mode_ceiling, NeuralMode
        ):
            raise ValueError("admission_effective_mode_ceiling_must_be_neural_mode")
        if self.output is not None:
            object.__setattr__(self, "output", _json_value(self.output))


@dataclass(frozen=True, slots=True)
class NeuralInferenceResult:
    inference_id: str
    run_id: str
    organ: str
    capability: str
    requested_mode: NeuralMode
    effective_mode: NeuralMode
    candidate_output: Any
    effective_output: Any
    confidence: float
    uncertainty: float
    device: str
    latency_ms: float
    cost: Mapping[str, Any]
    manifest_sha256: str | None
    fallback_used: bool
    fallback_reason: str | None
    decision_influence: DecisionInfluence
    causal_linkage: CausalLinkage
    trace: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class OrganismImpactVector:
    closure_rate: float
    certification_rate: float
    continuity: float
    viability: float
    latency_ms: float
    cpu_pressure: float
    memory_pressure: float
    vram_gb: float
    thermal_pressure: float
    safety_violations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "closure_rate": self.closure_rate,
            "certification_rate": self.certification_rate,
            "continuity": self.continuity,
            "viability": self.viability,
            "latency_ms": self.latency_ms,
            "cpu_pressure": self.cpu_pressure,
            "memory_pressure": self.memory_pressure,
            "vram_gb": self.vram_gb,
            "thermal_pressure": self.thermal_pressure,
            "safety_violations": self.safety_violations,
        }


@dataclass(frozen=True, slots=True)
class OrganismImpactReport:
    organ: str
    model_id: str
    seeds: tuple[int, ...]
    baseline: OrganismImpactVector
    candidate: OrganismImpactVector
    primary_metric_delta: float
    primary_metric_ci95: tuple[float, float]
    ece: float | None = None
    interactions: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organ": self.organ,
            "model_id": self.model_id,
            "seeds": list(self.seeds),
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "primary_metric_delta": self.primary_metric_delta,
            "primary_metric_ci95": list(self.primary_metric_ci95),
            "ece": self.ece,
            "interactions": dict(self.interactions),
            "promotion_eligible": self.promotion_eligible(),
        }

    def promotion_eligible(
        self,
        *,
        closure_tolerance: float = 0.01,
        certification_tolerance: float = 0.01,
        continuity_tolerance: float = 0.01,
        viability_tolerance: float = 0.01,
        max_ece: float = 0.10,
        max_latency_ms: float = 5_000.0,
        max_vram_gb: float = 6.0,
        max_pressure: float = 0.85,
    ) -> bool:
        return bool(
            len(set(self.seeds)) >= 3
            and self.primary_metric_ci95[0] > 0.0
            and self.candidate.closure_rate
            >= self.baseline.closure_rate - closure_tolerance
            and self.candidate.certification_rate
            >= self.baseline.certification_rate - certification_tolerance
            and self.candidate.continuity
            >= self.baseline.continuity - continuity_tolerance
            and self.candidate.viability
            >= self.baseline.viability - viability_tolerance
            and self.candidate.safety_violations == 0
            and (self.ece is None or self.ece <= max_ece)
            and self.candidate.latency_ms <= max_latency_ms
            and self.candidate.vram_gb <= max_vram_gb
            and self.candidate.cpu_pressure <= max_pressure
            and self.candidate.memory_pressure <= max_pressure
            and self.candidate.thermal_pressure <= max_pressure
        )


@runtime_checkable
class NeuralBackend(Protocol):
    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None: ...

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput: ...

    def unload(self) -> None: ...


@runtime_checkable
class OrganAdapter(Protocol):
    organ: str
    capability: str

    def build_request(self, context: Mapping[str, Any]) -> NeuralInferenceRequest: ...

    def deterministic_fallback(self, request: NeuralInferenceRequest) -> Any: ...

    def admit(self, candidate: Any, request: NeuralInferenceRequest) -> AdmissionDecision: ...
