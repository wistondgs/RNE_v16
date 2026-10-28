"""Interfaces de persistencia para runtime/storage."""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .records import (
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


@runtime_checkable
class LedgerStore(Protocol):
    def append_event(self, event: StoredEvent) -> StoredEvent:
        ...

    def list_events(
        self,
        *,
        limit: int = 200,
        event_types: Sequence[str] | None = None,
        run_id: str | None = None,
    ) -> list[StoredEvent]:
        ...


@runtime_checkable
class TelemetryStore(Protocol):
    def write_telemetry_snapshot(
        self, snapshot: TelemetrySnapshotRecord
    ) -> TelemetrySnapshotRecord:
        ...

    def list_telemetry_snapshots(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[TelemetrySnapshotRecord]:
        ...


@runtime_checkable
class ReasoningTraceStore(Protocol):
    def append_reasoning_trace(
        self, trace: ReasoningTraceRecord
    ) -> ReasoningTraceRecord:
        ...

    def list_reasoning_traces(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[ReasoningTraceRecord]:
        ...


@runtime_checkable
class ArtifactIndexStore(Protocol):
    def register_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        ...

    def list_artifacts(
        self,
        *,
        run_id: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[ArtifactRecord]:
        ...


@runtime_checkable
class SessionStore(Protocol):
    """Capacidad reservada (B23): session bridge implementado en toda la capa de
    storage pero SIN productores/consumidores en el runtime actual. No remover sin
    decision de producto."""

    def upsert_session_bridge(
        self, record: SessionBridgeRecord
    ) -> SessionBridgeRecord:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        ...

    def get_session_bridge(self, session_id: str) -> SessionBridgeRecord | None:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        ...


@runtime_checkable
class RealityStore(Protocol):
    def write_reality_assessment(
        self, assessment: RealityAssessmentRecord
    ) -> RealityAssessmentRecord:
        ...

    def list_reality_assessments(
        self,
        *,
        run_id: str | None = None,
        bench_run_id: str | None = None,
        limit: int = 200,
    ) -> list[RealityAssessmentRecord]:
        ...

    def write_reality_bench_run(
        self, bench_run: RealityBenchRunRecord
    ) -> RealityBenchRunRecord:
        ...

    def list_reality_bench_runs(
        self, *, run_id: str | None = None, limit: int = 50
    ) -> list[RealityBenchRunRecord]:
        ...


@runtime_checkable
class CertificationStore(Protocol):
    def write_episode_certificate(
        self, certificate: EpisodeCertificateRecord
    ) -> EpisodeCertificateRecord:
        ...

    def get_episode_certificate(
        self, *, certificate_id: str | None = None, episode_id: str | None = None
    ) -> EpisodeCertificateRecord | None:
        ...

    def list_episode_certificates(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[EpisodeCertificateRecord]:
        ...

    def write_promotion_decision(
        self, decision: PromotionDecisionRecord
    ) -> PromotionDecisionRecord:
        ...

    def list_promotion_decisions(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[PromotionDecisionRecord]:
        ...


@runtime_checkable
class MemoryStore(Protocol):
    def write_memory_record(self, memory: MemoryRecord) -> MemoryRecord:
        ...

    def retrieve_memory_records(
        self,
        *,
        run_id: str | None = None,
        scales: Sequence[str] | None = None,
        min_ioc_proxy: float | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        ...

    def purge_expired_memory_records(self) -> int:
        """Borra las memorias expiradas (TTL) y devuelve la cantidad borrada."""
        ...


@runtime_checkable
class TransferAssessmentStore(Protocol):
    def write_transfer_assessment(
        self, assessment: TransferAssessmentRecord
    ) -> TransferAssessmentRecord:
        ...

    def list_transfer_assessments(
        self,
        *,
        run_id: str | None = None,
        episode_id: str | None = None,
        limit: int = 200,
    ) -> list[TransferAssessmentRecord]:
        ...


@runtime_checkable
class T4TrajectoryStore(Protocol):
    def write_organism_snapshot(
        self, snapshot: OrganismSnapshotRecord
    ) -> OrganismSnapshotRecord:
        ...

    def list_organism_snapshots(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[OrganismSnapshotRecord]:
        ...

    def write_trajectory_window(
        self, window: TrajectoryWindowRecord
    ) -> TrajectoryWindowRecord:
        ...

    def list_trajectory_windows(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryWindowRecord]:
        ...

    def write_trajectory_flow_report(
        self, report: TrajectoryFlowReportRecord
    ) -> TrajectoryFlowReportRecord:
        ...

    def list_trajectory_flow_reports(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryFlowReportRecord]:
        ...

    def write_renormalization_event(
        self, event: RenormalizationEventRecord
    ) -> RenormalizationEventRecord:
        ...

    def list_renormalization_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[RenormalizationEventRecord]:
        ...

    def write_constitutional_risk_state(
        self, risk_state: ConstitutionalRiskStateRecord
    ) -> ConstitutionalRiskStateRecord:
        ...

    def list_constitutional_risk_states(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[ConstitutionalRiskStateRecord]:
        ...

    def write_failure_atlas_event(
        self, event: FailureAtlasEventRecord
    ) -> FailureAtlasEventRecord:
        ...

    def list_failure_atlas_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[FailureAtlasEventRecord]:
        ...


@runtime_checkable
class StorageBackend(
    LedgerStore,
    TelemetryStore,
    ReasoningTraceStore,
    ArtifactIndexStore,
    SessionStore,
    RealityStore,
    CertificationStore,
    MemoryStore,
    TransferAssessmentStore,
    T4TrajectoryStore,
    Protocol,
):
    def close(self) -> None:
        ...
