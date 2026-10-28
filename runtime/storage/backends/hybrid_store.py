"""Backend hibrido para dual-write (PostgreSQL + SQLite)."""

from __future__ import annotations

import logging
from typing import Sequence

from ..interfaces import StorageBackend

logger = logging.getLogger(__name__)
from ..records import (
    ArtifactRecord,
    ConstitutionalRiskStateRecord,
    EpisodeCertificateRecord,
    FailureAtlasEventRecord,
    MemoryRecord,
    OrganismSnapshotRecord,
    PromotionDecisionRecord,
    RenormalizationEventRecord,
    ReasoningTraceRecord,
    RealityAssessmentRecord,
    RealityBenchRunRecord,
    SessionBridgeRecord,
    StoredEvent,
    TelemetrySnapshotRecord,
    TrajectoryFlowReportRecord,
    TrajectoryWindowRecord,
    TransferAssessmentRecord,
)


class HybridStorageBackend(StorageBackend):
    """Escribe en ambos stores y lee con prioridad configurable."""

    def __init__(
        self,
        *,
        primary: StorageBackend,
        fallback: StorageBackend,
        prefer_primary_reads: bool = True,
        strict_dual_write: bool = False,
    ):
        self.primary = primary
        self.fallback = fallback
        self.prefer_primary_reads = prefer_primary_reads
        self.strict_dual_write = strict_dual_write

    def _dual_write(self, method: str, payload: object) -> object:
        primary_error: Exception | None = None
        fallback_error: Exception | None = None
        primary_result: object | None = None
        fallback_result: object | None = None

        try:
            primary_result = getattr(self.primary, method)(payload)
        except Exception as exc:  # pragma: no cover - cubierto en integracion
            primary_error = exc

        try:
            fallback_result = getattr(self.fallback, method)(payload)
        except Exception as exc:  # pragma: no cover - cubierto en integracion
            fallback_error = exc

        if self.strict_dual_write and (primary_error or fallback_error):
            errors = [e for e in (primary_error, fallback_error) if e]
            raise RuntimeError(
                f"Dual-write estricto fallo en {method}: {[str(e) for e in errors]}"
            )

        # Resiliencia dual-write no estricta: si un store falla pero el otro
        # responde, devolvemos el resultado bueno. El error del store caido NO
        # se propaga; lo hacemos observable con un warning (metodo + cual store).
        if primary_result is not None:
            if fallback_error is not None:
                logger.warning(
                    "dual-write %s: el store fallback fallo pero el primary "
                    "respondio; error descartado (strict_dual_write=False): %r",
                    method,
                    fallback_error,
                )
            return primary_result
        if fallback_result is not None:
            if primary_error is not None:
                logger.warning(
                    "dual-write %s: el store primary fallo pero el fallback "
                    "respondio; error descartado (strict_dual_write=False): %r",
                    method,
                    primary_error,
                )
            return fallback_result
        if primary_error and fallback_error:
            raise RuntimeError(
                f"Dual-write fallo en {method}: {primary_error}; {fallback_error}"
            )
        if primary_error:
            raise primary_error
        if fallback_error:
            raise fallback_error
        return payload

    def _read_with_fallback(self, method: str, **kwargs: object) -> list:
        first = self.primary if self.prefer_primary_reads else self.fallback
        second = self.fallback if self.prefer_primary_reads else self.primary
        first_label = "primary" if self.prefer_primary_reads else "fallback"
        try:
            rows = getattr(first, method)(**kwargs)
            if rows:
                return rows
        except Exception as exc:  # pragma: no cover - cubierto en integracion
            # El error del store preferido se traga al caer al secundario;
            # lo hacemos observable con un warning (metodo + cual store).
            logger.warning(
                "read %s: el store %s fallo; se recurre al store secundario. "
                "Error descartado: %r",
                method,
                first_label,
                exc,
            )
        return getattr(second, method)(**kwargs)

    def append_event(self, event: StoredEvent) -> StoredEvent:
        return self._dual_write("append_event", event)  # type: ignore[return-value]

    def list_events(
        self,
        *,
        limit: int = 200,
        event_types: Sequence[str] | None = None,
        run_id: str | None = None,
    ) -> list[StoredEvent]:
        return self._read_with_fallback(
            "list_events",
            limit=limit,
            event_types=event_types,
            run_id=run_id,
        )

    def write_telemetry_snapshot(
        self, snapshot: TelemetrySnapshotRecord
    ) -> TelemetrySnapshotRecord:
        return self._dual_write("write_telemetry_snapshot", snapshot)  # type: ignore[return-value]

    def list_telemetry_snapshots(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[TelemetrySnapshotRecord]:
        return self._read_with_fallback(
            "list_telemetry_snapshots",
            run_id=run_id,
            limit=limit,
        )

    def append_reasoning_trace(
        self, trace: ReasoningTraceRecord
    ) -> ReasoningTraceRecord:
        return self._dual_write("append_reasoning_trace", trace)  # type: ignore[return-value]

    def list_reasoning_traces(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[ReasoningTraceRecord]:
        return self._read_with_fallback(
            "list_reasoning_traces",
            run_id=run_id,
            limit=limit,
        )

    def register_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        return self._dual_write("register_artifact", artifact)  # type: ignore[return-value]

    def list_artifacts(
        self,
        *,
        run_id: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[ArtifactRecord]:
        return self._read_with_fallback(
            "list_artifacts",
            run_id=run_id,
            kind=kind,
            limit=limit,
        )

    def upsert_session_bridge(
        self, record: SessionBridgeRecord
    ) -> SessionBridgeRecord:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        return self._dual_write("upsert_session_bridge", record)  # type: ignore[return-value]

    def get_session_bridge(self, session_id: str) -> SessionBridgeRecord | None:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        first = self.primary if self.prefer_primary_reads else self.fallback
        second = self.fallback if self.prefer_primary_reads else self.primary
        first_label = "primary" if self.prefer_primary_reads else "fallback"
        try:
            row = first.get_session_bridge(session_id)
            if row is not None:
                return row
        except Exception as exc:  # pragma: no cover - cubierto en integracion
            logger.warning(
                "read get_session_bridge: el store %s fallo; se recurre al "
                "store secundario. Error descartado: %r",
                first_label,
                exc,
            )
        return second.get_session_bridge(session_id)

    def write_reality_assessment(
        self, assessment: RealityAssessmentRecord
    ) -> RealityAssessmentRecord:
        return self._dual_write("write_reality_assessment", assessment)  # type: ignore[return-value]

    def list_reality_assessments(
        self,
        *,
        run_id: str | None = None,
        bench_run_id: str | None = None,
        limit: int = 200,
    ) -> list[RealityAssessmentRecord]:
        return self._read_with_fallback(
            "list_reality_assessments",
            run_id=run_id,
            bench_run_id=bench_run_id,
            limit=limit,
        )

    def write_reality_bench_run(
        self, bench_run: RealityBenchRunRecord
    ) -> RealityBenchRunRecord:
        return self._dual_write("write_reality_bench_run", bench_run)  # type: ignore[return-value]

    def list_reality_bench_runs(
        self, *, run_id: str | None = None, limit: int = 50
    ) -> list[RealityBenchRunRecord]:
        return self._read_with_fallback(
            "list_reality_bench_runs",
            run_id=run_id,
            limit=limit,
        )

    def write_episode_certificate(
        self, certificate: EpisodeCertificateRecord
    ) -> EpisodeCertificateRecord:
        return self._dual_write("write_episode_certificate", certificate)  # type: ignore[return-value]

    def get_episode_certificate(
        self, *, certificate_id: str | None = None, episode_id: str | None = None
    ) -> EpisodeCertificateRecord | None:
        first = self.primary if self.prefer_primary_reads else self.fallback
        second = self.fallback if self.prefer_primary_reads else self.primary
        first_label = "primary" if self.prefer_primary_reads else "fallback"
        try:
            row = first.get_episode_certificate(
                certificate_id=certificate_id,
                episode_id=episode_id,
            )
            if row is not None:
                return row
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "read get_episode_certificate: el store %s fallo; se recurre "
                "al store secundario. Error descartado: %r",
                first_label,
                exc,
            )
        return second.get_episode_certificate(
            certificate_id=certificate_id,
            episode_id=episode_id,
        )

    def list_episode_certificates(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[EpisodeCertificateRecord]:
        return self._read_with_fallback(
            "list_episode_certificates",
            run_id=run_id,
            limit=limit,
        )

    def write_promotion_decision(
        self, decision: PromotionDecisionRecord
    ) -> PromotionDecisionRecord:
        return self._dual_write("write_promotion_decision", decision)  # type: ignore[return-value]

    def list_promotion_decisions(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[PromotionDecisionRecord]:
        return self._read_with_fallback(
            "list_promotion_decisions",
            run_id=run_id,
            limit=limit,
        )

    def write_memory_record(self, memory: MemoryRecord) -> MemoryRecord:
        return self._dual_write("write_memory_record", memory)  # type: ignore[return-value]

    def retrieve_memory_records(
        self,
        *,
        run_id: str | None = None,
        scales: Sequence[str] | None = None,
        min_ioc_proxy: float | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        return self._read_with_fallback(
            "retrieve_memory_records",
            run_id=run_id,
            scales=scales,
            min_ioc_proxy=min_ioc_proxy,
            limit=limit,
        )

    def purge_expired_memory_records(self) -> int:
        # B2 - Purga en AMBOS stores (borrado físico en cada backend), pero devuelve la
        # cuenta LÓGICA (la del primary), no la suma: bajo dual-write cada memoria vive
        # en ambos stores, así que sumar contaría dos veces cada memoria lógica. El
        # fallback se purga igual (efecto físico); solo se descarta su conteo.
        deleted = self.primary.purge_expired_memory_records()
        self.fallback.purge_expired_memory_records()
        return deleted

    def write_transfer_assessment(
        self, assessment: TransferAssessmentRecord,
    ) -> TransferAssessmentRecord:
        return self._dual_write("write_transfer_assessment", assessment)  # type: ignore[return-value]

    def list_transfer_assessments(
        self,
        *,
        run_id: str | None = None,
        episode_id: str | None = None,
        limit: int = 200,
    ) -> list[TransferAssessmentRecord]:
        return self._read_with_fallback(
            "list_transfer_assessments",
            run_id=run_id,
            episode_id=episode_id,
            limit=limit,
        )

    def write_organism_snapshot(
        self, snapshot: OrganismSnapshotRecord
    ) -> OrganismSnapshotRecord:
        return self._dual_write("write_organism_snapshot", snapshot)  # type: ignore[return-value]

    def list_organism_snapshots(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[OrganismSnapshotRecord]:
        return self._read_with_fallback(
            "list_organism_snapshots",
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_trajectory_window(
        self, window: TrajectoryWindowRecord
    ) -> TrajectoryWindowRecord:
        return self._dual_write("write_trajectory_window", window)  # type: ignore[return-value]

    def list_trajectory_windows(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryWindowRecord]:
        return self._read_with_fallback(
            "list_trajectory_windows",
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_trajectory_flow_report(
        self, report: TrajectoryFlowReportRecord
    ) -> TrajectoryFlowReportRecord:
        return self._dual_write("write_trajectory_flow_report", report)  # type: ignore[return-value]

    def list_trajectory_flow_reports(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryFlowReportRecord]:
        return self._read_with_fallback(
            "list_trajectory_flow_reports",
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_renormalization_event(
        self, event: RenormalizationEventRecord
    ) -> RenormalizationEventRecord:
        return self._dual_write("write_renormalization_event", event)  # type: ignore[return-value]

    def list_renormalization_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[RenormalizationEventRecord]:
        return self._read_with_fallback(
            "list_renormalization_events",
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_constitutional_risk_state(
        self, risk_state: ConstitutionalRiskStateRecord
    ) -> ConstitutionalRiskStateRecord:
        return self._dual_write("write_constitutional_risk_state", risk_state)  # type: ignore[return-value]

    def list_constitutional_risk_states(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[ConstitutionalRiskStateRecord]:
        return self._read_with_fallback(
            "list_constitutional_risk_states",
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            limit=limit,
        )

    def write_failure_atlas_event(
        self, event: FailureAtlasEventRecord
    ) -> FailureAtlasEventRecord:
        return self._dual_write("write_failure_atlas_event", event)  # type: ignore[return-value]

    def list_failure_atlas_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[FailureAtlasEventRecord]:
        return self._read_with_fallback(
            "list_failure_atlas_events",
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            limit=limit,
        )

    def close(self) -> None:
        self.primary.close()
        self.fallback.close()
