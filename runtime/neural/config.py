"""Configuracion segura del runtime neuronal."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePosixPath

from .contracts import DevicePreference, NeuralMode


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class NeuralRuntimeConfig:
    mode: NeuralMode = NeuralMode.OFF
    device_preference: DevicePreference = DevicePreference.AUTO
    artifact_namespace: str = "neural"
    max_resident_vram_gb: float = 6.0
    min_free_vram_gb: float = 1.5
    reject_vram_pressure: float = 0.80
    unload_vram_pressure: float = 0.85
    max_gpu_temperature_c: float = 82.0
    max_latency_ms: float = 5_000.0
    trace_buffer_size: int = 128
    require_causal_for_provisional: bool = True
    allow_runtime_downloads: bool = False

    def __post_init__(self) -> None:
        if self.allow_runtime_downloads:
            raise ValueError("runtime_downloads_are_forbidden")
        namespace = PurePosixPath(self.artifact_namespace)
        if (
            not self.artifact_namespace
            or namespace.is_absolute()
            or ".." in namespace.parts
        ):
            raise ValueError("artifact_namespace_must_be_relative")
        if self.max_resident_vram_gb <= 0.0 or self.min_free_vram_gb < 0.0:
            raise ValueError("invalid_vram_budget")
        if not 0.0 < self.reject_vram_pressure < self.unload_vram_pressure <= 1.0:
            raise ValueError("invalid_vram_pressure_thresholds")
        if self.max_latency_ms <= 0.0:
            raise ValueError("max_latency_ms_must_be_positive")
        if self.trace_buffer_size <= 0:
            raise ValueError("trace_buffer_size_must_be_positive")

    @classmethod
    def from_env(cls) -> "NeuralRuntimeConfig":
        raw_mode = os.environ.get("RNFE_NEURAL_MODE", "off").strip().lower()
        raw_device = os.environ.get("RNFE_NEURAL_DEVICE", "auto").strip().lower()
        try:
            mode = NeuralMode(raw_mode)
        except ValueError:
            mode = NeuralMode.OFF
        try:
            device = DevicePreference(raw_device)
        except ValueError:
            device = DevicePreference.AUTO
        return cls(
            mode=mode,
            device_preference=device,
            artifact_namespace=os.environ.get("RNFE_NEURAL_ARTIFACT_NAMESPACE", "neural"),
            max_resident_vram_gb=_float_env("RNFE_NEURAL_MAX_VRAM_GB", 6.0),
            min_free_vram_gb=_float_env("RNFE_NEURAL_MIN_FREE_VRAM_GB", 1.5),
            reject_vram_pressure=_float_env("RNFE_NEURAL_REJECT_VRAM_PRESSURE", 0.80),
            unload_vram_pressure=_float_env("RNFE_NEURAL_UNLOAD_VRAM_PRESSURE", 0.85),
            max_gpu_temperature_c=_float_env("RNFE_NEURAL_MAX_GPU_TEMP_C", 82.0),
            max_latency_ms=_float_env("RNFE_NEURAL_MAX_LATENCY_MS", 5_000.0),
            trace_buffer_size=max(
                1,
                int(_float_env("RNFE_NEURAL_TRACE_BUFFER_SIZE", 128.0)),
            ),
        )
