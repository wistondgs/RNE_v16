"""Fachada de alto nivel para persistencia del runtime."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .config import StorageConfig
from .contract_validation import enforce_event, enforce_record
from .interfaces import StorageBackend
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
    utc_now_iso,
)


class StorageFacade:
    """API estable y backend-agnostica para runtime y exocortex."""

    def __init__(self, *, backend: StorageBackend, config: StorageConfig):
        self.backend = backend
        self.config = config

    def append_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any] | None,
        timestamp: str | None = None,
        run_id: str | None = None,
        source: str | None = None,
        legacy_db_path: str | None = None,
        legacy_event_id: int | None = None,
        event_id: str | None = None,
    ) -> StoredEvent:
        event = StoredEvent(
            event_id=event_id,
            run_id=run_id,
            event_type=event_type,
            payload=dict(payload or {}),
            timestamp=timestamp or utc_now_iso(),
            source=source,
            legacy_db_path=legacy_db_path,
            legacy_event_id=legacy_event_id,
        )
        # B17: contrato activo (CANON §13). Los contratos episodio/propuesta/rollback
        # viajan como payload de evento; se validan ANTES de persistir.
        enforce_event(event_type, event.payload, origin="StorageFacade.append_event")
        return self.backend.append_event(event)

    def list_events(
        self,
        *,
        limit: int = 200,
        event_types: Sequence[str] | None = None,
        run_id: str | None = None,
    ) -> list[StoredEvent]:
        return self.backend.list_events(limit=limit, event_types=event_types, run_id=run_id)

    def write_telemetry_snapshot(
        self,
        *,
        metrics: Mapping[str, Any],
        snapshot_id: str | None = None,
        timestamp: str | None = None,
        run_id: str | None = None,
    ) -> TelemetrySnapshotRecord:
        record = TelemetrySnapshotRecord(
            snapshot_id=snapshot_id or str(uuid4()),
            run_id=run_id,
            metrics=dict(metrics),
            timestamp=timestamp or utc_now_iso(),
        )
        # B17: contrato activo (CANON §13).
        enforce_record(
            "telemetry_snapshot",
            record,
            origin="StorageFacade.write_telemetry_snapshot",
        )
        return self.backend.write_telemetry_snapshot(record)

    def list_telemetry_snapshots(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[TelemetrySnapshotRecord]:
        return self.backend.list_telemetry_snapshots(run_id=run_id, limit=limit)

    def append_reasoning_trace(
        self,
        *,
        family: str,
        status: str,
        step_index: int,
        detail: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
        timestamp: str | None = None,
        run_id: str | None = None,
    ) -> ReasoningTraceRecord:
        record = ReasoningTraceRecord(
            trace_id=trace_id or str(uuid4()),
            run_id=run_id,
            step_index=step_index,
            family=family,
            status=status,
            detail=dict(detail or {}),
            timestamp=timestamp or utc_now_iso(),
        )
        return self.backend.append_reasoning_trace(record)

    def list_reasoning_traces(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[ReasoningTraceRecord]:
        return self.backend.list_reasoning_traces(run_id=run_id, limit=limit)

    def register_artifact(
        self,
        *,
        kind: str,
        abs_path: str | Path,
        run_id: str | None = None,
        artifact_id: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ArtifactRecord:
        path = Path(abs_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Artifact path invalida: {path}")

        content = path.read_bytes()
        digest = sha256 or hashlib.sha256(content).hexdigest()
        size = size_bytes if size_bytes is not None else len(content)
        guessed_mime = mime_type or mimetypes.guess_type(path.name)[0]
        try:
            rel_path = str(path.relative_to(self.config.artifact_root))
        except ValueError:
            rel_path = path.name

        record = ArtifactRecord(
            artifact_id=artifact_id or str(uuid4()),
            run_id=run_id,
            kind=kind,
            rel_path=rel_path,
            abs_path=str(path),
            sha256=digest,
            size_bytes=size,
            mime_type=guessed_mime,
            metadata=dict(metadata or {}),
            created_at=created_at or utc_now_iso(),
        )
        return self.backend.register_artifact(record)

    def materialize_artifact(
        self,
        *,
        run_id: str | None,
        kind: str,
        content: bytes | str | Path,
        filename: str | None = None,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRecord:
        if isinstance(content, Path):
            raw = content.read_bytes()
            suffix = content.suffix
        elif isinstance(content, str):
            raw = content.encode("utf-8")
            suffix = Path(filename).suffix if filename else ".txt"
        else:
            raw = bytes(content)
            suffix = Path(filename).suffix if filename else ".bin"

        digest = hashlib.sha256(raw).hexdigest()
        run_segment = run_id or "no-run"
        base_dir = self.config.artifact_root / run_segment / kind / digest[:2] / digest[2:4]
        base_dir.mkdir(parents=True, exist_ok=True)
        target = base_dir / f"{digest}{suffix}"
        target.write_bytes(raw)
        return self.register_artifact(
            kind=kind,
            abs_path=target,
            run_id=run_id,
            sha256=digest,
            size_bytes=len(raw),
            mime_type=mime_type,
            metadata=metadata,
        )

    def list_artifacts(
        self,
        *,
        run_id: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[ArtifactRecord]:
        return self.backend.list_artifacts(run_id=run_id, kind=kind, limit=limit)

    def upsert_session_bridge(
        self,
        *,
        session_id: str,
        episode_id: str,
        channel: str,
        timestamp: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> SessionBridgeRecord:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        record = SessionBridgeRecord(
            session_id=session_id,
            episode_id=episode_id,
            channel=channel,
            timestamp=timestamp or utc_now_iso(),
            metadata=dict(metadata or {}),
        )
        return self.backend.upsert_session_bridge(record)

    def get_session_bridge(self, session_id: str) -> SessionBridgeRecord | None:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        return self.backend.get_session_bridge(session_id)

    def write_reality_assessment(
        self,
        *,
        episode_id: str,
        closure_passed: bool,
        continuity_score: float,
        trace_integrity: bool,
        collapse_detected: bool,
        run_id: str | None = None,
        bench_run_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        assessment_id: str | None = None,
        created_at: str | None = None,
    ) -> RealityAssessmentRecord:
        record = RealityAssessmentRecord(
            assessment_id=assessment_id or str(uuid4()),
            episode_id=episode_id,
            closure_passed=bool(closure_passed),
            continuity_score=float(continuity_score),
            trace_integrity=bool(trace_integrity),
            collapse_detected=bool(collapse_detected),
            created_at=created_at or utc_now_iso(),
            run_id=run_id,
            bench_run_id=bench_run_id,
            details=dict(details or {}),
        )
        return self.backend.write_reality_assessment(record)

    def list_reality_assessments(
        self,
        *,
        run_id: str | None = None,
        bench_run_id: str | None = None,
        limit: int = 200,
    ) -> list[RealityAssessmentRecord]:
        return self.backend.list_reality_assessments(
            run_id=run_id,
            bench_run_id=bench_run_id,
            limit=limit,
        )

    def write_reality_bench_run(
        self,
        *,
        total_episodes: int,
        closure_rate: float,
        continuity_mean: float,
        collapse_count: int,
        gate_profile: str,
        passed: bool,
        run_id: str | None = None,
        summary: Mapping[str, Any] | None = None,
        bench_run_id: str | None = None,
        created_at: str | None = None,
    ) -> RealityBenchRunRecord:
        record = RealityBenchRunRecord(
            bench_run_id=bench_run_id or str(uuid4()),
            total_episodes=int(total_episodes),
            closure_rate=float(closure_rate),
            continuity_mean=float(continuity_mean),
            collapse_count=int(collapse_count),
            gate_profile=gate_profile,
            passed=bool(passed),
            created_at=created_at or utc_now_iso(),
            run_id=run_id,
            summary=dict(summary or {}),
        )
        return self.backend.write_reality_bench_run(record)

    def list_reality_bench_runs(
        self, *, run_id: str | None = None, limit: int = 50
    ) -> list[RealityBenchRunRecord]:
        return self.backend.list_reality_bench_runs(run_id=run_id, limit=limit)

    def write_episode_certificate(
        self,
        *,
        episode_id: str,
        run_id: str,
        trace_id: str,
        smg_artifacts: Mapping[str, Any],
        lotf_artifacts: Mapping[str, Any],
        world_artifacts: Mapping[str, Any],
        continuity_score: float,
        ioc_proxy: float,
        risk_score: float,
        verdict: str,
        rollback_ready: bool,
        promotion_candidate: bool,
        metadata: Mapping[str, Any] | None = None,
        certificate_id: str | None = None,
        created_at: str | None = None,
    ) -> EpisodeCertificateRecord:
        record = EpisodeCertificateRecord(
            certificate_id=certificate_id or str(uuid4()),
            episode_id=episode_id,
            run_id=run_id,
            trace_id=trace_id,
            smg_artifacts=dict(smg_artifacts),
            lotf_artifacts=dict(lotf_artifacts),
            world_artifacts=dict(world_artifacts),
            continuity_score=float(continuity_score),
            ioc_proxy=float(ioc_proxy),
            risk_score=float(risk_score),
            verdict=verdict,
            rollback_ready=bool(rollback_ready),
            promotion_candidate=bool(promotion_candidate),
            created_at=created_at or utc_now_iso(),
            metadata=dict(metadata or {}),
        )
        # B17: contrato activo (CANON §13).
        enforce_record(
            "certificate",
            record,
            origin="StorageFacade.write_episode_certificate",
        )
        return self.backend.write_episode_certificate(record)

    def get_episode_certificate(
        self, *, certificate_id: str | None = None, episode_id: str | None = None
    ) -> EpisodeCertificateRecord | None:
        return self.backend.get_episode_certificate(
            certificate_id=certificate_id, episode_id=episode_id
        )

    def list_episode_certificates(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[EpisodeCertificateRecord]:
        return self.backend.list_episode_certificates(run_id=run_id, limit=limit)

    def write_promotion_decision(
        self,
        *,
        episode_id: str,
        run_id: str,
        certificate_id: str,
        verdict: str,
        reason: str,
        rollback_ready: bool,
        metadata: Mapping[str, Any] | None = None,
        decision_id: str | None = None,
        created_at: str | None = None,
    ) -> PromotionDecisionRecord:
        record = PromotionDecisionRecord(
            decision_id=decision_id or str(uuid4()),
            episode_id=episode_id,
            run_id=run_id,
            certificate_id=certificate_id,
            verdict=verdict,
            reason=reason,
            rollback_ready=bool(rollback_ready),
            created_at=created_at or utc_now_iso(),
            metadata=dict(metadata or {}),
        )
        return self.backend.write_promotion_decision(record)

    def list_promotion_decisions(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[PromotionDecisionRecord]:
        return self.backend.list_promotion_decisions(run_id=run_id, limit=limit)

    def write_memory_record(
        self,
        *,
        run_id: str,
        episode_id: str,
        scale: str,
        structure_json: Mapping[str, Any],
        ttl_seconds: int | None = None,
        # B24: NO computado. El default `True` es un default de schema (columna
        # NOT NULL), no una medición: nadie verifica la no-interferencia y nadie
        # lee este campo. No confiar en él. Ver runtime/storage/records.py.
        no_interference: bool = True,
        certificate_id: str | None = None,
        ioc_proxy: float | None = None,
        support_count: int = 0,
        metadata: Mapping[str, Any] | None = None,
        memory_id: str | None = None,
        created_at: str | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            memory_id=memory_id or str(uuid4()),
            run_id=run_id,
            episode_id=episode_id,
            scale=scale,
            structure_json=dict(structure_json),
            ttl_seconds=ttl_seconds,
            no_interference=bool(no_interference),
            certificate_id=certificate_id,
            ioc_proxy=float(ioc_proxy) if ioc_proxy is not None else None,
            support_count=int(support_count),
            created_at=created_at or utc_now_iso(),
            # B24: marcador LEGIBLE POR MÁQUINA de que `no_interference` NO está computado.
            # Declararlo solo en comentarios no alcanza: un consumidor programático —o un
            # analista leyendo el ledger por SQL— ve `no_interference = True` y no tiene
            # forma de distinguirlo de una medición real. Eso es exactamente lo que el
            # paquete de honestidad (P9) vino a prohibir, así que la declaración tiene que
            # viajar EN LOS DATOS, no en la prosa.
            # Contract-safe: `contracts/memory_record.schema.json:26` declara `metadata` como
            # object sin `additionalProperties: false` -> la clave es aditiva.
            # El día que alguien compute de verdad la no-interferencia, esto pasa a True.
            metadata={**dict(metadata or {}), "no_interference_computed": False},
        )
        return self.backend.write_memory_record(record)

    def retrieve_memory_records(
        self,
        *,
        run_id: str | None = None,
        scales: Sequence[str] | None = None,
        min_ioc_proxy: float | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        return self.backend.retrieve_memory_records(
            run_id=run_id,
            scales=scales,
            min_ioc_proxy=min_ioc_proxy,
            limit=limit,
        )

    def purge_expired_memory_records(self) -> int:
        """B2 - Borra memorias expiradas por TTL; devuelve la cantidad borrada."""
        return self.backend.purge_expired_memory_records()

    # ───────────────  Transfer Assessment  ────────────────────────────────────

    def write_transfer_assessment(
        self,
        *,
        assessment_id: str,
        run_id: str,
        episode_id: str,
        source_scenario: str,
        target_scenario: str,
        compatibility_class: str,
        transfer_verdict: str,
        memory_purity_score: float,
        transition_stability_score: float,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> TransferAssessmentRecord:
        record = TransferAssessmentRecord(
            assessment_id=assessment_id,
            run_id=run_id,
            episode_id=episode_id,
            source_scenario=source_scenario,
            target_scenario=target_scenario,
            compatibility_class=compatibility_class,
            transfer_verdict=transfer_verdict,
            memory_purity_score=float(memory_purity_score),
            transition_stability_score=float(transition_stability_score),
            created_at=created_at or utc_now_iso(),
            metadata=dict(metadata or {}),
        )
        return self.backend.write_transfer_assessment(record)

    def list_transfer_assessments(
        self,
        *,
        run_id: str | None = None,
        episode_id: str | None = None,
        limit: int = 200,
    ) -> list[TransferAssessmentRecord]:
        return self.backend.list_transfer_assessments(
            run_id=run_id,
            episode_id=episode_id,
            limit=limit,
        )

    # ───────────────  T4 trajectory stores  ───────────────────────────────────

    def write_organism_snapshot(
        self,
        *,
        snapshot_id: str,
        run_id: str,
        episode_id: str,
        trajectory_id: str,
        regime: str,
        snapshot_json: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> OrganismSnapshotRecord:
        record = OrganismSnapshotRecord(
            snapshot_id=snapshot_id,
            run_id=run_id,
            episode_id=episode_id,
            trajectory_id=trajectory_id,
            regime=regime,
            snapshot_json=dict(snapshot_json),
            created_at=created_at or utc_now_iso(),
            metadata=dict(metadata or {}),
        )
        return self.backend.write_organism_snapshot(record)

    def list_organism_snapshots(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[OrganismSnapshotRecord]:
        return self.backend.list_organism_snapshots(
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_trajectory_window(
        self,
        *,
        window_id: str,
        run_id: str,
        trajectory_id: str,
        start_episode: int,
        end_episode: int,
        snapshots_json: Mapping[str, Any],
        digest_json: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> TrajectoryWindowRecord:
        record = TrajectoryWindowRecord(
            window_id=window_id,
            run_id=run_id,
            trajectory_id=trajectory_id,
            start_episode=int(start_episode),
            end_episode=int(end_episode),
            snapshots_json=dict(snapshots_json),
            digest_json=dict(digest_json),
            metadata=dict(metadata or {}),
            created_at=created_at or utc_now_iso(),
        )
        return self.backend.write_trajectory_window(record)

    def list_trajectory_windows(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryWindowRecord]:
        return self.backend.list_trajectory_windows(
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_trajectory_flow_report(
        self,
        *,
        report_id: str,
        run_id: str,
        trajectory_id: str,
        window_id: str,
        flow_validity: bool,
        erosion: float,
        phase_drift: float,
        rollback_obligation: bool,
        report_json: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> TrajectoryFlowReportRecord:
        record = TrajectoryFlowReportRecord(
            report_id=report_id,
            run_id=run_id,
            trajectory_id=trajectory_id,
            window_id=window_id,
            flow_validity=bool(flow_validity),
            erosion=float(erosion),
            phase_drift=float(phase_drift),
            rollback_obligation=bool(rollback_obligation),
            report_json=dict(report_json),
            metadata=dict(metadata or {}),
            created_at=created_at or utc_now_iso(),
        )
        return self.backend.write_trajectory_flow_report(record)

    def list_trajectory_flow_reports(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryFlowReportRecord]:
        return self.backend.list_trajectory_flow_reports(
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_renormalization_event(
        self,
        *,
        event_id: str,
        run_id: str,
        trajectory_id: str,
        source_regime: str,
        target_regime: str,
        residual_error: float,
        transport_uncertainty: float,
        expected_recovery_cost: float,
        map_json: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> RenormalizationEventRecord:
        record = RenormalizationEventRecord(
            event_id=event_id,
            run_id=run_id,
            trajectory_id=trajectory_id,
            source_regime=source_regime,
            target_regime=target_regime,
            residual_error=float(residual_error),
            transport_uncertainty=float(transport_uncertainty),
            expected_recovery_cost=float(expected_recovery_cost),
            map_json=dict(map_json),
            metadata=dict(metadata or {}),
            created_at=created_at or utc_now_iso(),
        )
        return self.backend.write_renormalization_event(record)

    def list_renormalization_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[RenormalizationEventRecord]:
        return self.backend.list_renormalization_events(
            run_id=run_id,
            trajectory_id=trajectory_id,
            limit=limit,
        )

    def write_constitutional_risk_state(
        self,
        *,
        state_id: str,
        run_id: str,
        trajectory_id: str,
        scope_type: str,
        scope_key: str,
        risk_score: float,
        risk_json: Mapping[str, Any],
        prev_state_id: str | None = None,
        step_index: int = 0,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ConstitutionalRiskStateRecord:
        record = ConstitutionalRiskStateRecord(
            state_id=state_id,
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            risk_score=float(risk_score),
            risk_json=dict(risk_json),
            prev_state_id=prev_state_id,
            step_index=int(step_index),
            metadata=dict(metadata or {}),
            created_at=created_at or utc_now_iso(),
        )
        return self.backend.write_constitutional_risk_state(record)

    def list_constitutional_risk_states(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[ConstitutionalRiskStateRecord]:
        return self.backend.list_constitutional_risk_states(
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            limit=limit,
        )

    def write_failure_atlas_event(
        self,
        *,
        event_id: str,
        run_id: str,
        trajectory_id: str,
        scope_type: str,
        scope_key: str,
        failure_class: str,
        severity: str,
        reversible: bool,
        recovery_protocol: str,
        signature_json: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> FailureAtlasEventRecord:
        record = FailureAtlasEventRecord(
            event_id=event_id,
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            failure_class=failure_class,
            severity=severity,
            reversible=bool(reversible),
            recovery_protocol=recovery_protocol,
            signature_json=dict(signature_json),
            metadata=dict(metadata or {}),
            created_at=created_at or utc_now_iso(),
        )
        return self.backend.write_failure_atlas_event(record)

    def list_failure_atlas_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[FailureAtlasEventRecord]:
        return self.backend.list_failure_atlas_events(
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            limit=limit,
        )

    def close(self) -> None:
        self.backend.close()
