"""Orquestador N0: modos, recursos, fallback y observabilidad."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from .config import NeuralRuntimeConfig
from .contracts import (
    AdmissionDecision,
    CausalLinkage,
    DecisionInfluence,
    InferenceScope,
    NeuralInferenceRequest,
    NeuralInferenceResult,
    NeuralMode,
    NeuralModelManifest,
    OrganismImpactReport,
)
from .registry import LazyBackendRegistry
from .resources import select_device, should_unload
from .observability import BufferedTraceEvent, TraceHealthSnapshot, TracePersistenceMonitor


AdmissionGate = Callable[[Any, NeuralInferenceRequest], AdmissionDecision]


class NeuralRuntime:
    def __init__(
        self,
        *,
        config: NeuralRuntimeConfig,
        registry: LazyBackendRegistry,
        storage: Any | None = None,
    ):
        self.config = config
        self.registry = registry
        self.storage = storage
        self._trace_monitor = TracePersistenceMonitor(
            storage_configured=storage is not None,
            max_buffered_events=config.trace_buffer_size,
        )

    def infer(
        self,
        *,
        request: NeuralInferenceRequest,
        manifest: NeuralModelManifest,
        fallback_output: Any,
        admission_gate: AdmissionGate | None = None,
    ) -> NeuralInferenceResult:
        requested_mode = self.config.mode
        if requested_mode is NeuralMode.OFF:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.OFF,
                fallback_output=fallback_output,
                reason="neural_mode_off",
                emit_event=False,
            )
        self._persist_event(
            "neural.inference.requested",
            payload={
                "inference_id": request.inference_id,
                "organ": request.organ,
                "capability": request.capability,
                "requested_mode": requested_mode.value,
                "manifest_sha256": manifest.manifest_sha256,
                "causal_linkage": request.causal_linkage.value,
            },
            run_id=request.run_id,
        )
        if request.organ != manifest.organ or request.capability != manifest.capability:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.OFF,
                fallback_output=fallback_output,
                reason="request_manifest_contract_mismatch",
            )
        if requested_mode is NeuralMode.EXPERIMENTAL and request.scope is InferenceScope.LIVE:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.EXPERIMENTAL,
                fallback_output=fallback_output,
                reason="experimental_mode_is_lab_only",
            )

        effective_mode = requested_mode
        context = request.causal_context
        if (
            requested_mode is NeuralMode.PROVISIONAL
            and self.config.require_causal_for_provisional
            and (context is None or not context.permits_decision_influence)
        ):
            effective_mode = NeuralMode.SHADOW

        device_decision = select_device(self.config, manifest, request.resources)
        if device_decision.device is None:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                fallback_output=fallback_output,
                reason=device_decision.reason,
                manifest_sha256=manifest.manifest_sha256,
            )

        started = time.perf_counter()
        backend_key: tuple[str, str, str] | None = None
        try:
            backend, backend_key, newly_loaded = self.registry.acquire(
                manifest,
                device=device_decision.device,
            )
            if newly_loaded:
                self._emit_model_event(
                    "neural.model.loaded",
                    request=request,
                    manifest=manifest,
                    device=device_decision.device,
                )
            output = backend.infer(request)
        except Exception as exc:
            if backend_key is not None:
                self.registry.unload(backend_key)
                self._emit_model_event(
                    "neural.model.unloaded",
                    request=request,
                    manifest=manifest,
                    device=device_decision.device,
                    reason=_exception_reason(exc),
                )
            else:
                self._emit_model_event(
                    "neural.model.rejected",
                    request=request,
                    manifest=manifest,
                    device=device_decision.device,
                    reason=_exception_reason(exc),
                )
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                fallback_output=fallback_output,
                reason=_exception_reason(exc),
                device=device_decision.device,
                manifest_sha256=manifest.manifest_sha256,
                latency_ms=(time.perf_counter() - started) * 1_000.0,
            )

        latency_ms = (time.perf_counter() - started) * 1_000.0
        if (
            backend_key is not None
            and device_decision.device == "cuda"
            and should_unload(self.config, request.resources)
        ):
            self.registry.unload(backend_key)
            self._emit_model_event(
                "neural.model.unloaded",
                request=request,
                manifest=manifest,
                device=device_decision.device,
                reason="resource_pressure",
            )
        if latency_ms > self.config.max_latency_ms:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                fallback_output=fallback_output,
                reason="latency_budget_exceeded",
                device=device_decision.device,
                manifest_sha256=manifest.manifest_sha256,
                latency_ms=latency_ms,
                candidate_output=output.candidate_output,
                confidence=output.confidence,
                uncertainty=output.uncertainty,
                cost=output.cost,
                trace=output.trace,
            )

        effective_output = fallback_output
        influence = DecisionInfluence.NONE
        fallback_used = True
        fallback_reason: str | None = None
        if effective_mode is NeuralMode.PROVISIONAL:
            if admission_gate is None:
                effective_mode = NeuralMode.SHADOW
                fallback_reason = "missing_admission_gate"
            else:
                try:
                    decision = admission_gate(output.candidate_output, request)
                except Exception as exc:
                    decision = None
                    effective_mode = NeuralMode.SHADOW
                    fallback_reason = f"admission_gate_failed:{_exception_reason(exc)}"
                if decision is not None and not isinstance(decision, AdmissionDecision):
                    effective_mode = NeuralMode.SHADOW
                    fallback_reason = "admission_contract_invalid"
                elif decision is not None and decision.accepted:
                    ceiling = decision.effective_mode_ceiling
                    if ceiling is NeuralMode.SHADOW:
                        effective_mode = NeuralMode.SHADOW
                        fallback_reason = "admission_authority_ceiling:shadow"
                    elif ceiling is not None and not isinstance(ceiling, NeuralMode):
                        effective_mode = NeuralMode.SHADOW
                        fallback_reason = "admission_authority_ceiling_invalid:type"
                    elif ceiling not in {None, NeuralMode.PROVISIONAL}:
                        effective_mode = NeuralMode.SHADOW
                        fallback_reason = f"admission_authority_ceiling_invalid:{ceiling.value}"
                    else:
                        effective_output = (
                            decision.output
                            if decision.output is not None
                            else output.candidate_output
                        )
                        influence = DecisionInfluence.BOUNDED_PROPOSAL
                        fallback_used = False
                elif decision is not None:
                    fallback_reason = decision.reason or "admission_rejected"
        elif effective_mode is NeuralMode.SHADOW:
            fallback_reason = (
                "causal_context_unlinked"
                if requested_mode is NeuralMode.PROVISIONAL
                else "shadow_preserves_authoritative_output"
            )
        else:
            fallback_reason = "experimental_candidate_only"

        result = NeuralInferenceResult(
            inference_id=request.inference_id,
            run_id=request.run_id,
            organ=request.organ,
            capability=request.capability,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            candidate_output=output.candidate_output,
            effective_output=effective_output,
            confidence=output.confidence,
            uncertainty=output.uncertainty,
            device=device_decision.device,
            latency_ms=latency_ms,
            cost=output.cost,
            manifest_sha256=manifest.manifest_sha256,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            decision_influence=influence,
            causal_linkage=request.causal_linkage,
            trace=output.trace,
        )
        self._emit("neural.inference.completed", result)
        if result.effective_mode is NeuralMode.SHADOW:
            self._persist_event(
                "neural.organ.shadow_evaluated",
                payload={
                    "inference_id": result.inference_id,
                    "organ": result.organ,
                    "manifest_sha256": result.manifest_sha256,
                    "candidate_present": result.candidate_output is not None,
                    "authoritative_output_preserved": result.decision_influence
                    is DecisionInfluence.NONE,
                    "fallback_reason": result.fallback_reason,
                },
                run_id=result.run_id,
            )
        return result

    def infer_reference(
        self,
        *,
        request: NeuralInferenceRequest,
        producer: Callable[[NeuralInferenceRequest], Any],
        fallback_output: Any,
        reference_id: str,
        authority_ceiling: NeuralMode = NeuralMode.SHADOW,
        admission_gate: AdmissionGate | None = None,
        enabled: bool = True,
    ) -> NeuralInferenceResult:
        """Ejecuta un algoritmo determinista honesto bajo las garantías de N0.

        Este puerto existe para capacidades que ya tienen lógica CPU real pero no un
        artefacto entrenado. No fabrica un ``NeuralModelManifest`` ni presenta el
        algoritmo como modelo: ``reference_id`` se firma como identidad de código y los
        campos de manifest/artefacto permanecen ausentes en la traza simbiótica.
        """

        requested_mode = self.config.mode
        if requested_mode is NeuralMode.OFF:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.OFF,
                fallback_output=fallback_output,
                reason="neural_mode_off",
                emit_event=False,
            )
        if not enabled:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.OFF,
                fallback_output=fallback_output,
                reason="organ_disabled_by_profile",
            )
        if requested_mode is NeuralMode.EXPERIMENTAL and request.scope is InferenceScope.LIVE:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.EXPERIMENTAL,
                fallback_output=fallback_output,
                reason="experimental_mode_is_lab_only",
            )
        if not request.resources.msrc_budget_available:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.SHADOW,
                fallback_output=fallback_output,
                reason="msrc_budget_unavailable",
            )
        # Degradación ordenada: N5/N3 son puertos CPU mínimos de ingestión y
        # continuidad; las propuestas opcionales se abstienen bajo presión alta.
        pressure = max(
            request.resources.cpu_pressure,
            request.resources.memory_pressure,
            request.resources.thermal_pressure,
            (
                request.resources.vram_pressure
                if request.resources.gpu_available
                else 0.0
            ),
        )
        if (
            request.organ in {"N1", "N2", "N4", "N6"}
            and pressure >= self.config.reject_vram_pressure
        ):
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=NeuralMode.SHADOW,
                fallback_output=fallback_output,
                reason="reference_degraded_by_resource_pressure",
            )

        reference_sha256 = hashlib.sha256(reference_id.encode("utf-8")).hexdigest()
        effective_mode = _minimum_mode(requested_mode, authority_ceiling)
        if effective_mode is NeuralMode.PROVISIONAL:
            context = request.causal_context
            if (
                self.config.require_causal_for_provisional
                and (context is None or not context.permits_decision_influence)
            ):
                effective_mode = NeuralMode.SHADOW

        self._persist_event(
            "neural.reference.requested",
            payload={
                "inference_id": request.inference_id,
                "organ": request.organ,
                "capability": request.capability,
                "reference_id": reference_id,
                "reference_sha256": reference_sha256,
                "requested_mode": requested_mode.value,
            },
            run_id=request.run_id,
        )
        started = time.perf_counter()
        try:
            raw_output = producer(request)
            output = raw_output if hasattr(raw_output, "candidate_output") else None
            candidate = output.candidate_output if output is not None else raw_output
            confidence = float(getattr(output, "confidence", 1.0))
            uncertainty = float(getattr(output, "uncertainty", 0.0))
            cost = {
                **dict(getattr(output, "cost", {}) or {}),
                "reference_id": reference_id,
                "reference_sha256": reference_sha256,
            }
            trace = tuple(getattr(output, "trace", ()) or ())
        except Exception as exc:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                fallback_output=fallback_output,
                reason=_exception_reason(exc),
                manifest_sha256=None,
                latency_ms=(time.perf_counter() - started) * 1_000.0,
            )

        latency_ms = (time.perf_counter() - started) * 1_000.0
        if latency_ms > self.config.max_latency_ms:
            return self._fallback(
                request,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                fallback_output=fallback_output,
                reason="latency_budget_exceeded",
                manifest_sha256=None,
                latency_ms=latency_ms,
                candidate_output=candidate,
                confidence=confidence,
                uncertainty=uncertainty,
                cost=cost,
                trace=trace,
            )

        admission: AdmissionDecision | None = None
        fallback_used = False
        fallback_reason: str | None = None
        admitted_output = candidate
        if admission_gate is not None:
            try:
                admission = admission_gate(candidate, request)
            except Exception as exc:
                fallback_used = True
                fallback_reason = f"admission_gate_failed:{_exception_reason(exc)}"
            else:
                if not isinstance(admission, AdmissionDecision):
                    fallback_used = True
                    fallback_reason = "admission_contract_invalid"
                    admission = None
                elif not admission.accepted:
                    fallback_used = True
                    fallback_reason = admission.reason or "admission_rejected"
                else:
                    admitted_output = (
                        admission.output if admission.output is not None else candidate
                    )
                    if admission.effective_mode_ceiling is not None:
                        effective_mode = _minimum_mode(
                            effective_mode, admission.effective_mode_ceiling
                        )

        influence = DecisionInfluence.NONE
        effective_output = fallback_output
        if admission is not None and admission.accepted and effective_mode is NeuralMode.PROVISIONAL:
            effective_output = admitted_output
            influence = DecisionInfluence.BOUNDED_PROPOSAL
        elif effective_mode is NeuralMode.SHADOW and fallback_reason is None:
            fallback_reason = "reference_authority_ceiling:shadow"

        result = NeuralInferenceResult(
            inference_id=request.inference_id,
            run_id=request.run_id,
            organ=request.organ,
            capability=request.capability,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            candidate_output=candidate,
            # Una salida shadow es evidencia consumible, no salida autoritativa.
            effective_output=effective_output,
            confidence=min(max(confidence, 0.0), 1.0),
            uncertainty=min(max(uncertainty, 0.0), 1.0),
            device="cpu",
            latency_ms=latency_ms,
            cost=cost,
            manifest_sha256=None,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            decision_influence=influence,
            causal_linkage=request.causal_linkage,
            trace=trace,
        )
        self._emit("neural.reference.completed", result)
        return result

    def persist_symbiosis_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        run_id: str,
    ) -> bool:
        """Persiste trazas del coordinador usando el mismo health/buffer de N0."""

        return self._persist_event(event_type, payload=payload, run_id=run_id)

    @property
    def trace_health(self) -> TraceHealthSnapshot:
        return self._trace_monitor.snapshot()

    def flush_trace_buffer(self) -> int:
        if self.storage is None:
            return 0
        pending = self._trace_monitor.pending()
        if not pending:
            return 0
        health = self._trace_monitor.snapshot()
        summary = self._trace_monitor.new_event(
            event_type="neural.trace.persistence_failed",
            payload={
                "schema_version": "neural-events-v1",
                "persistence_failures": health.persistence_failures,
                "pending_events": health.pending_events,
                "dropped_events": health.dropped_events,
                "last_error": health.last_error,
                "last_failure_at": health.last_failure_at,
                "recovery": "storage_available",
            },
            run_id=pending[-1].run_id,
        )
        try:
            self._append_trace_event(summary)
        except Exception as exc:
            self._trace_monitor.record_flush_failure(exc)
            return 0
        flushed = 0
        for event in pending:
            try:
                self._append_trace_event(event)
            except Exception as exc:
                self._trace_monitor.mark_flushed(flushed)
                self._trace_monitor.record_flush_failure(exc)
                return flushed
            flushed += 1
        self._trace_monitor.mark_flushed(flushed)
        return flushed

    def persist_manifest(self, manifest: NeuralModelManifest, *, run_id: str | None = None) -> Any:
        if self.storage is None:
            raise RuntimeError("storage_is_required_to_persist_manifest")
        return self.storage.materialize_artifact(
            run_id=run_id,
            kind="neural-model-manifest",
            content=manifest.canonical_json(),
            filename=f"{manifest.model_id}.manifest.json",
            mime_type="application/json",
            metadata={
                "organ": manifest.organ,
                "model_id": manifest.model_id,
                "manifest_sha256": manifest.manifest_sha256,
            },
        )

    def persist_impact_report(self, report: OrganismImpactReport, *, run_id: str) -> Any:
        if self.storage is None:
            raise RuntimeError("storage_is_required_to_persist_impact_report")
        content = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
        artifact = self.storage.materialize_artifact(
            run_id=run_id,
            kind="neural-organism-impact",
            content=content,
            filename=f"{report.organ}-{report.model_id}.impact.json",
            mime_type="application/json",
            metadata={
                "organ": report.organ,
                "model_id": report.model_id,
                "promotion_eligible": report.promotion_eligible(),
            },
        )
        self._persist_event(
            "neural.organ.promotion_evaluated",
            payload={
                "organ": report.organ,
                "model_id": report.model_id,
                "promotion_eligible": report.promotion_eligible(),
                "artifact_sha256": artifact.sha256,
            },
            run_id=run_id,
        )
        return artifact

    def _fallback(
        self,
        request: NeuralInferenceRequest,
        *,
        requested_mode: NeuralMode,
        effective_mode: NeuralMode,
        fallback_output: Any,
        reason: str,
        device: str = "none",
        manifest_sha256: str | None = None,
        latency_ms: float = 0.0,
        candidate_output: Any = None,
        confidence: float = 0.0,
        uncertainty: float = 1.0,
        cost: Any = None,
        trace: Any = (),
        emit_event: bool = True,
    ) -> NeuralInferenceResult:
        result = NeuralInferenceResult(
            inference_id=request.inference_id,
            run_id=request.run_id,
            organ=request.organ,
            capability=request.capability,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            candidate_output=candidate_output,
            effective_output=fallback_output,
            confidence=confidence,
            uncertainty=uncertainty,
            device=device,
            latency_ms=latency_ms,
            cost=cost or {},
            manifest_sha256=manifest_sha256,
            fallback_used=True,
            fallback_reason=reason,
            decision_influence=DecisionInfluence.NONE,
            causal_linkage=request.causal_linkage,
            trace=tuple(trace),
        )
        if emit_event:
            self._persist_event(
                "neural.inference.rejected",
                payload={
                    "inference_id": result.inference_id,
                    "organ": result.organ,
                    "capability": result.capability,
                    "reason": result.fallback_reason,
                    "device": result.device,
                    "manifest_sha256": result.manifest_sha256,
                },
                run_id=result.run_id,
            )
            self._emit("neural.inference.fallback", result)
        return result

    def _emit(self, event_type: str, result: NeuralInferenceResult) -> None:
        payload = {
            "inference_id": result.inference_id,
            "organ": result.organ,
            "capability": result.capability,
            "requested_mode": result.requested_mode.value,
            "effective_mode": result.effective_mode.value,
            "device": result.device,
            "latency_ms": round(result.latency_ms, 6),
            "manifest_sha256": result.manifest_sha256,
            "fallback_used": result.fallback_used,
            "fallback_reason": result.fallback_reason,
            "decision_influence": result.decision_influence.value,
            "causal_linkage": result.causal_linkage.value,
        }
        self._persist_event(event_type, payload=payload, run_id=result.run_id)

    def _emit_model_event(
        self,
        event_type: str,
        *,
        request: NeuralInferenceRequest,
        manifest: NeuralModelManifest,
        device: str,
        reason: str | None = None,
    ) -> None:
        self._persist_event(
            event_type,
            payload={
                "inference_id": request.inference_id,
                "organ": manifest.organ,
                "model_id": manifest.model_id,
                "manifest_sha256": manifest.manifest_sha256,
                "device": device,
                "reason": reason,
            },
            run_id=request.run_id,
        )

    def _persist_event(
        self,
        event_type: str,
        *,
        payload: dict[str, Any],
        run_id: str | None,
    ) -> bool:
        if self.storage is None:
            return False
        event = self._trace_monitor.new_event(
            event_type=event_type,
            payload={"schema_version": "neural-events-v1", **payload},
            run_id=run_id,
        )
        try:
            self._append_trace_event(event)
        except Exception as exc:
            # La inferencia continua, pero la perdida queda visible y recuperable.
            self._trace_monitor.record_failure(event, exc)
            return False
        if self._trace_monitor.pending():
            self.flush_trace_buffer()
        return True

    def _append_trace_event(self, event: BufferedTraceEvent) -> Any:
        return self.storage.append_event(
            event_type=event.event_type,
            payload=event.payload,
            timestamp=event.timestamp,
            run_id=event.run_id,
            source=event.source,
        )


def _is_oom(exc: BaseException) -> bool:
    return isinstance(exc, MemoryError) or "out of memory" in str(exc).lower()


_MODE_RANK = {
    NeuralMode.OFF: 0,
    NeuralMode.EXPERIMENTAL: 1,
    NeuralMode.SHADOW: 2,
    NeuralMode.PROVISIONAL: 3,
}


def _minimum_mode(*modes: NeuralMode) -> NeuralMode:
    if not modes or any(not isinstance(mode, NeuralMode) for mode in modes):
        raise ValueError("reference_mode_ceiling_invalid")
    return min(modes, key=_MODE_RANK.__getitem__)


def _exception_reason(exc: BaseException) -> str:
    if _is_oom(exc):
        return "backend_out_of_memory"
    name = exc.__class__.__name__.lower()
    message = str(exc).strip().replace(" ", "_")[:160]
    return f"backend_error:{name}:{message}" if message else f"backend_error:{name}"
