from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from runtime.neural import (
    CausalContextView,
    CausalLinkage,
    NeuralModelManifest,
    OrganismImpactReport,
    OrganismImpactVector,
    ResourceSnapshot,
)


def _manifest(digest: str) -> NeuralModelManifest:
    return NeuralModelManifest(
        organ="n1",
        capability="family_routing",
        model_id="router-test",
        version="1.0.0",
        backend="fixture",
        artifact_path="n1/router.bin",
        artifact_sha256=digest,
        input_schema_version="1",
        output_schema_version="1",
        supported_devices=("cpu", "cuda", "cpu"),
        parameter_count=128,
        peak_vram_gb=0.1,
        license_id="Unlicense",
        upstream_url="repo://rnfe/runtime/neural",
        upstream_commit="test-commit",
        training_provenance={"dataset": "fixture", "seed": 7},
    )


def test_manifest_is_canonical_and_rejects_unsafe_paths() -> None:
    digest = hashlib.sha256(b"weights").hexdigest()
    manifest = _manifest(digest)

    assert manifest.organ == "N1"
    assert manifest.supported_devices == ("cpu", "cuda")
    assert len(manifest.manifest_sha256) == 64
    assert NeuralModelManifest.from_dict(manifest.to_dict()) == manifest

    with pytest.raises(ValueError, match="safe_relative"):
        replace(manifest, artifact_path="../escape.bin")
    with pytest.raises(ValueError, match="lowercase_sha256"):
        replace(manifest, artifact_sha256="bad")


def test_causal_context_distinguishes_decision_link_from_complete_chain() -> None:
    assert CausalContextView().linkage is CausalLinkage.UNLINKED
    decision = CausalContextView(organism_id="org", decision_id="dec")
    assert decision.linkage is CausalLinkage.DECISION_LINKED
    assert decision.permits_decision_influence is True
    complete = replace(
        decision,
        episode_id="ep",
        trace_id="trace",
        certificate_id="cert",
    )
    assert complete.linkage is CausalLinkage.COMPLETE


def test_resource_snapshot_maps_current_and_future_telemetry_names() -> None:
    snapshot = ResourceSnapshot.from_mapping(
        {
            "available": True,
            "used_gb": 1.0,
            "total_gb": 8.0,
            "temperature_c": 70,
            "vram_pressure": 0.125,
        }
    )
    assert snapshot.gpu_available is True
    assert snapshot.vram_used_gb == 1.0
    assert snapshot.vram_total_gb == 8.0
    assert snapshot.gpu_temperature_c == 70.0


def test_a_m0_impact_report_rejects_local_gain_with_global_damage() -> None:
    baseline = OrganismImpactVector(0.90, 0.90, 0.8, 0.8, 10, 0.2, 0.2, 0.0, 0.1)
    candidate = OrganismImpactVector(0.87, 0.92, 0.82, 0.82, 11, 0.2, 0.2, 1.0, 0.1)
    report = OrganismImpactReport(
        organ="N1",
        model_id="router-test",
        seeds=(1, 2, 3),
        baseline=baseline,
        candidate=candidate,
        primary_metric_delta=0.02,
        primary_metric_ci95=(0.01, 0.03),
        ece=0.05,
    )
    assert report.promotion_eligible() is False

    safe = replace(candidate, closure_rate=0.895)
    assert replace(report, candidate=safe).promotion_eligible() is True

    locally_better_but_discontinuous = replace(safe, continuity=0.5)
    assert replace(report, candidate=locally_better_but_discontinuous).promotion_eligible() is False
