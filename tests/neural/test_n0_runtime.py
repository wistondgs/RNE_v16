from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from runtime.neural import (
    AdmissionDecision,
    BackendOutput,
    CausalContextView,
    DecisionInfluence,
    DevicePreference,
    InferenceScope,
    LazyBackendRegistry,
    NeuralInferenceRequest,
    NeuralMode,
    NeuralModelManifest,
    NeuralRuntime,
    NeuralRuntimeConfig,
    OrganismImpactReport,
    OrganismImpactVector,
    ResourceSnapshot,
)
from runtime.storage import StorageConfig, StorageFactory


class FixtureBackend:
    def __init__(self, counters: dict[str, int], *, fail_oom: bool = False):
        self.counters = counters
        self.fail_oom = fail_oom

    def load(self, manifest, artifact_path: str, device: str) -> None:
        assert Path(artifact_path).is_file()
        self.counters["load"] = self.counters.get("load", 0) + 1

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        self.counters["infer"] = self.counters.get("infer", 0) + 1
        if self.fail_oom:
            raise MemoryError("fixture out of memory")
        return BackendOutput(
            candidate_output={"families": ["IND"], "seed": request.seed},
            confidence=0.8,
            uncertainty=0.2,
            cost={"ops": 3},
        )

    def unload(self) -> None:
        self.counters["unload"] = self.counters.get("unload", 0) + 1


class FlakyStorage:
    def __init__(self) -> None:
        self.fail = True
        self.events = []

    def append_event(self, **kwargs):
        if self.fail:
            raise OSError("fixture-storage-unavailable")
        self.events.append(dict(kwargs))
        return kwargs


def _manifest(root: Path, *, digest_override: str | None = None) -> NeuralModelManifest:
    target = root / "n1" / "router.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fixture-weights")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return NeuralModelManifest(
        organ="N1",
        capability="family_routing",
        model_id="router-test",
        version="1.0.0",
        backend="fixture",
        artifact_path="n1/router.bin",
        artifact_sha256=digest_override or digest,
        input_schema_version="1",
        output_schema_version="1",
        supported_devices=("cpu", "cuda"),
        parameter_count=128,
        peak_vram_gb=0.5,
        license_id="Unlicense",
        upstream_url="repo://rnfe/runtime/neural",
        upstream_commit="test-commit",
        training_provenance={"dataset": "fixture", "seed": 7},
    )


def _request(*, linked: bool = False, scope: InferenceScope = InferenceScope.LIVE):
    causal = CausalContextView(organism_id="org", decision_id="dec") if linked else None
    return NeuralInferenceRequest(
        inference_id="inf-1",
        run_id="run-1",
        organ="N1",
        capability="family_routing",
        payload={"features": [0.1, 0.2]},
        seed=11,
        scope=scope,
        resources=ResourceSnapshot(),
        causal_context=causal,
    )


def _runtime(
    tmp_path: Path,
    mode: NeuralMode,
    counters,
    *,
    fail_oom=False,
    storage=None,
    trace_buffer_size=128,
):
    root = tmp_path / "artifacts" / "neural"
    registry = LazyBackendRegistry(artifact_root=root)
    registry.register("fixture", lambda: FixtureBackend(counters, fail_oom=fail_oom))
    runtime = NeuralRuntime(
        config=NeuralRuntimeConfig(
            mode=mode,
            device_preference=DevicePreference.CPU,
            trace_buffer_size=trace_buffer_size,
        ),
        registry=registry,
        storage=storage,
    )
    return runtime, registry, _manifest(root)


def test_importing_neural_does_not_import_torch() -> None:
    code = "import sys; import runtime.neural; print(int('torch' in sys.modules))"
    proc = subprocess.run([sys.executable, "-c", code], check=True, text=True, capture_output=True)
    assert proc.stdout.strip() == "0"


def test_off_never_loads_backend_or_emits_event(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    storage = StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "events.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "store",
            prefer_postgres_reads=True,
            strict_dual_write=False,
        )
    )
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.OFF, counters, storage=storage)
    result = runtime.infer(request=_request(), manifest=manifest, fallback_output={"families": ["DED"]})
    assert result.effective_output == {"families": ["DED"]}
    assert counters == {}
    assert storage.list_events(run_id="run-1") == []
    storage.close()


def test_shadow_persists_candidate_but_preserves_fallback(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, registry, manifest = _runtime(tmp_path, NeuralMode.SHADOW, counters)
    result = runtime.infer(request=_request(), manifest=manifest, fallback_output={"families": ["DED"]})
    assert result.candidate_output == {"families": ["IND"], "seed": 11}
    assert result.effective_output == {"families": ["DED"]}
    assert result.decision_influence is DecisionInfluence.NONE
    assert result.fallback_reason == "shadow_preserves_authoritative_output"
    assert counters == {"load": 1, "infer": 1}
    assert registry.loaded_count == 1


def test_provisional_without_causal_context_downgrades_to_shadow(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.PROVISIONAL, counters)
    result = runtime.infer(
        request=_request(),
        manifest=manifest,
        fallback_output={"families": ["DED"]},
        admission_gate=lambda candidate, request: AdmissionDecision(True, candidate),
    )
    assert result.effective_mode is NeuralMode.SHADOW
    assert result.effective_output == {"families": ["DED"]}
    assert result.fallback_reason == "causal_context_unlinked"


def test_linked_provisional_only_exposes_admitted_bounded_proposal(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.PROVISIONAL, counters)
    result = runtime.infer(
        request=_request(linked=True),
        manifest=manifest,
        fallback_output={"families": ["DED"]},
        admission_gate=lambda candidate, request: AdmissionDecision(
            True, {"families": ["DED", "IND"]}, "policy_validated"
        ),
    )
    assert result.effective_mode is NeuralMode.PROVISIONAL
    assert result.effective_output == {"families": ["DED", "IND"]}
    assert result.decision_influence is DecisionInfluence.BOUNDED_PROPOSAL
    assert result.fallback_used is False


def test_linked_provisional_honors_typed_shadow_authority_ceiling(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.PROVISIONAL, counters)
    fallback = {"families": ["DED"]}
    result = runtime.infer(
        request=_request(linked=True),
        manifest=manifest,
        fallback_output=fallback,
        admission_gate=lambda candidate, request: AdmissionDecision(
            True,
            candidate,
            "semantically_valid_but_shadow_only",
            effective_mode_ceiling=NeuralMode.SHADOW,
        ),
    )
    assert result.effective_mode is NeuralMode.SHADOW
    assert result.decision_influence is DecisionInfluence.NONE
    assert result.effective_output == fallback
    assert result.candidate_output == {"families": ["IND"], "seed": 11}
    assert result.fallback_used is True
    assert result.fallback_reason == "admission_authority_ceiling:shadow"


def test_rejected_or_invalid_admission_contract_fails_closed(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.PROVISIONAL, counters)
    fallback = {"families": ["DED"]}
    rejected = runtime.infer(
        request=_request(linked=True),
        manifest=manifest,
        fallback_output=fallback,
        admission_gate=lambda candidate, request: AdmissionDecision(
            False, reason="policy_rejected"
        ),
    )
    assert rejected.effective_output == fallback
    assert rejected.decision_influence is DecisionInfluence.NONE
    assert rejected.fallback_reason == "policy_rejected"

    def invalid_ceiling(candidate, request):
        return AdmissionDecision(
            True,
            candidate,
            "invalid_fixture",
            effective_mode_ceiling="shadow",  # type: ignore[arg-type]
        )

    invalid = runtime.infer(
        request=_request(linked=True),
        manifest=manifest,
        fallback_output=fallback,
        admission_gate=invalid_ceiling,
    )
    assert invalid.effective_mode is NeuralMode.SHADOW
    assert invalid.effective_output == fallback
    assert invalid.decision_influence is DecisionInfluence.NONE
    assert invalid.fallback_used is True
    assert "admission_effective_mode_ceiling_must_be_neural_mode" in (
        invalid.fallback_reason or ""
    )

    incompatible = runtime.infer(
        request=_request(linked=True),
        manifest=manifest,
        fallback_output=fallback,
        admission_gate=lambda candidate, request: AdmissionDecision(
            True,
            candidate,
            "experimental_is_not_a_live_authority_ceiling",
            effective_mode_ceiling=NeuralMode.EXPERIMENTAL,
        ),
    )
    assert incompatible.effective_mode is NeuralMode.SHADOW
    assert incompatible.effective_output == fallback
    assert incompatible.decision_influence is DecisionInfluence.NONE
    assert incompatible.fallback_reason == (
        "admission_authority_ceiling_invalid:experimental"
    )


def test_hash_mismatch_and_oom_are_explicit_fallbacks(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.SHADOW, counters)
    bad = NeuralModelManifest.from_dict(
        {**manifest.to_dict(), "artifact_sha256": "0" * 64}
    )
    result = runtime.infer(request=_request(), manifest=bad, fallback_output={"safe": True})
    assert result.fallback_used is True
    assert "artifact_sha256_mismatch" in (result.fallback_reason or "")

    oom_counters: dict[str, int] = {}
    oom_runtime, registry, oom_manifest = _runtime(
        tmp_path / "oom", NeuralMode.SHADOW, oom_counters, fail_oom=True
    )
    oom = oom_runtime.infer(
        request=_request(), manifest=oom_manifest, fallback_output={"safe": True}
    )
    assert oom.fallback_reason == "backend_out_of_memory"
    assert oom_counters == {"load": 1, "infer": 1, "unload": 1}
    assert registry.loaded_count == 0


def test_experimental_is_rejected_on_live_boundary(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.EXPERIMENTAL, counters)
    result = runtime.infer(request=_request(), manifest=manifest, fallback_output={"safe": True})
    assert result.fallback_reason == "experimental_mode_is_lab_only"
    assert counters == {}


def test_manifest_and_a_m0_report_use_existing_artifact_plane(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    storage = StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "impact.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "store",
            prefer_postgres_reads=True,
            strict_dual_write=False,
        )
    )
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.SHADOW, counters, storage=storage)
    manifest_artifact = runtime.persist_manifest(manifest, run_id="run-impact")
    baseline = OrganismImpactVector(0.9, 0.9, 0.8, 0.8, 10, 0.2, 0.2, 0.0, 0.1)
    candidate = OrganismImpactVector(0.9, 0.91, 0.81, 0.81, 11, 0.2, 0.2, 0.5, 0.1)
    report = OrganismImpactReport(
        organ="N1",
        model_id=manifest.model_id,
        seeds=(1, 2, 3),
        baseline=baseline,
        candidate=candidate,
        primary_metric_delta=0.01,
        primary_metric_ci95=(0.001, 0.02),
        ece=0.05,
    )
    impact_artifact = runtime.persist_impact_report(report, run_id="run-impact")
    assert Path(manifest_artifact.abs_path).is_file()
    assert Path(impact_artifact.abs_path).is_file()
    events = storage.list_events(run_id="run-impact")
    assert [event.event_type for event in events] == ["neural.organ.promotion_evaluated"]
    storage.close()


def test_trace_persistence_failure_is_buffered_reported_and_recovered(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    storage = FlakyStorage()
    runtime, _, manifest = _runtime(tmp_path, NeuralMode.SHADOW, counters, storage=storage)
    result = runtime.infer(
        request=_request(),
        manifest=manifest,
        fallback_output={"families": ["DED"]},
    )
    assert result.effective_output == {"families": ["DED"]}
    degraded = runtime.trace_health
    assert degraded.degraded is True
    assert degraded.persistence_failures == 4
    assert degraded.pending_events == 4
    assert degraded.last_error == "OSError:fixture-storage-unavailable"

    storage.fail = False
    assert runtime.flush_trace_buffer() == 4
    recovered = runtime.trace_health
    assert recovered.degraded is False
    assert recovered.pending_events == 0
    assert recovered.recovered_events == 4
    assert [event["event_type"] for event in storage.events] == [
        "neural.trace.persistence_failed",
        "neural.inference.requested",
        "neural.model.loaded",
        "neural.inference.completed",
        "neural.organ.shadow_evaluated",
    ]
    assert all(
        event["payload"]["schema_version"] == "neural-events-v1"
        for event in storage.events
    )


def test_trace_buffer_is_bounded_and_counts_dropped_events(tmp_path: Path) -> None:
    counters: dict[str, int] = {}
    storage = FlakyStorage()
    runtime, _, manifest = _runtime(
        tmp_path,
        NeuralMode.SHADOW,
        counters,
        storage=storage,
        trace_buffer_size=2,
    )
    runtime.infer(
        request=_request(),
        manifest=manifest,
        fallback_output={"families": ["DED"]},
    )
    health = runtime.trace_health
    assert health.persistence_failures == 4
    assert health.pending_events == 2
    assert health.dropped_events == 2
