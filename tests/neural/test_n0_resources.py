from __future__ import annotations

import hashlib

from runtime.neural import DevicePreference, NeuralModelManifest, NeuralRuntimeConfig, ResourceSnapshot
from runtime.neural.resources import select_device, should_unload


def _manifest(*, devices=("cpu", "cuda"), peak=2.0):
    return NeuralModelManifest(
        organ="N1",
        capability="family_routing",
        model_id="resource-test",
        version="1",
        backend="fixture",
        artifact_path="n1/model.bin",
        artifact_sha256=hashlib.sha256(b"x").hexdigest(),
        input_schema_version="1",
        output_schema_version="1",
        supported_devices=devices,
        peak_vram_gb=peak,
        license_id="Unlicense",
        upstream_url="repo://rnfe",
        upstream_commit="test",
        training_provenance={"fixture": True},
    )


def test_cuda_requires_absolute_telemetry_and_preserves_cpu_fallback() -> None:
    config = NeuralRuntimeConfig(device_preference=DevicePreference.AUTO)
    missing = ResourceSnapshot(gpu_available=True, vram_pressure=0.1)
    assert select_device(config, _manifest(), missing).device == "cpu"

    admitted = ResourceSnapshot(
        gpu_available=True,
        vram_pressure=0.25,
        vram_used_gb=2.0,
        vram_total_gb=8.0,
        gpu_temperature_c=70.0,
    )
    assert select_device(config, _manifest(), admitted).device == "cuda"


def test_cuda_budget_and_unload_pressure_are_enforced() -> None:
    config = NeuralRuntimeConfig(device_preference=DevicePreference.CUDA)
    resources = ResourceSnapshot(
        gpu_available=True,
        vram_pressure=0.2,
        vram_used_gb=2.0,
        vram_total_gb=8.0,
        gpu_temperature_c=70.0,
    )
    decision = select_device(config, _manifest(devices=("cuda",), peak=6.5), resources)
    assert decision.device is None
    assert decision.reason == "model_vram_budget_exceeded"
    assert should_unload(config, ResourceSnapshot(vram_pressure=0.9)) is True
