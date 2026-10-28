"""Politica de admision fisica para backends neuronales."""

from __future__ import annotations

from dataclasses import dataclass

from .config import NeuralRuntimeConfig
from .contracts import DevicePreference, NeuralModelManifest, ResourceSnapshot


@dataclass(frozen=True, slots=True)
class DeviceDecision:
    device: str | None
    reason: str


def select_device(
    config: NeuralRuntimeConfig,
    manifest: NeuralModelManifest,
    resources: ResourceSnapshot,
) -> DeviceDecision:
    supported = set(manifest.supported_devices)
    preference = config.device_preference

    if preference is not DevicePreference.CPU and "cuda" in supported:
        rejection = _cuda_rejection(config, manifest, resources)
        if rejection is None:
            return DeviceDecision("cuda", "cuda_admitted")
        if preference is DevicePreference.CUDA and "cpu" not in supported:
            return DeviceDecision(None, rejection)

    if "cpu" in supported and preference is not DevicePreference.CUDA:
        return DeviceDecision("cpu", "cpu_admitted")
    if "cpu" in supported and preference is DevicePreference.CUDA:
        return DeviceDecision("cpu", "cuda_rejected_cpu_fallback")
    return DeviceDecision(None, "no_supported_device_available")


def _cuda_rejection(
    config: NeuralRuntimeConfig,
    manifest: NeuralModelManifest,
    resources: ResourceSnapshot,
) -> str | None:
    if not resources.gpu_available:
        return "cuda_unavailable"
    if resources.vram_used_gb is None or resources.vram_total_gb is None:
        return "cuda_absolute_telemetry_missing"
    if resources.gpu_temperature_c is None:
        return "cuda_temperature_missing"
    if resources.vram_pressure >= config.reject_vram_pressure:
        return "cuda_vram_pressure_rejected"
    if resources.gpu_temperature_c >= config.max_gpu_temperature_c:
        return "cuda_temperature_rejected"
    if manifest.peak_vram_gb > config.max_resident_vram_gb:
        return "model_vram_budget_exceeded"
    projected_free = resources.vram_total_gb - resources.vram_used_gb - manifest.peak_vram_gb
    if projected_free < config.min_free_vram_gb:
        return "cuda_headroom_insufficient"
    return None


def should_unload(config: NeuralRuntimeConfig, resources: ResourceSnapshot) -> bool:
    return bool(
        resources.vram_pressure >= config.unload_vram_pressure
        or (
            resources.gpu_temperature_c is not None
            and resources.gpu_temperature_c >= config.max_gpu_temperature_c
        )
    )
