"""Backend PostgreSQL para storage RNFE."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..interfaces import StorageBackend
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


def _payload_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# B2 - created_at de memory_records es TEXT ISO-8601 UTC; se castea a timestamptz
# para medir el TTL. Edad en segundos = now() - created_at.
_MEMORY_AGE_SECONDS_SQL = "EXTRACT(EPOCH FROM (now() - created_at::timestamptz))"
# Condicion "NO expirada" para filtrar en lectura (ttl NULL = sin expiracion).
_MEMORY_NOT_EXPIRED_SQL = (
    f"(ttl_seconds IS NULL OR {_MEMORY_AGE_SECONDS_SQL} <= ttl_seconds)"
)
# Condicion "expirada" para purgar.
_MEMORY_EXPIRED_SQL = (
    f"ttl_seconds IS NOT NULL AND {_MEMORY_AGE_SECONDS_SQL} > ttl_seconds"
)


class PostgresStorageBackend(StorageBackend):
    """Store transaccional principal en PostgreSQL."""

    def __init__(self, dsn: str, schema_path: str | None = None):
        self.dsn = dsn
        if schema_path:
            self.schema_path = Path(schema_path)
        else:
            self.schema_path = Path(__file__).resolve().parent / "postgres" / "schema.sql"
        self._ensure_schema()

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _ensure_schema(self) -> None:
        ddl = self.schema_path.read_text(encoding="utf-8")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()

    def append_event(self, event: StoredEvent) -> StoredEvent:
        event_id = event.event_id or str(uuid4())
        payload = dict(event.payload or {})
        payload_hash = event.payload_hash or _payload_hash(payload)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger_events
                (event_id, run_id, event_type, payload_jsonb, event_ts, source,
                 legacy_db_path, legacy_event_id, payload_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING event_id
                """,
                (
                    event_id,
                    event.run_id,
                    event.event_type,
                    Jsonb(payload),
                    event.timestamp,
                    event.source,
                    event.legacy_db_path,
                    event.legacy_event_id,
                    payload_hash,
                ),
            )
            inserted = cur.fetchone()
            if not inserted and event.legacy_db_path and event.legacy_event_id is not None:
                cur.execute(
                    """
                    SELECT event_id
                    FROM ledger_events
                    WHERE legacy_db_path = %s AND legacy_event_id = %s
                    """,
                    (event.legacy_db_path, event.legacy_event_id),
                )
                found = cur.fetchone()
                if found:
                    event_id = found["event_id"]
            conn.commit()
        event.event_id = event_id
        event.payload_hash = payload_hash
        return event

    def list_events(
        self,
        *,
        limit: int = 200,
        event_types: Sequence[str] | None = None,
        run_id: str | None = None,
    ) -> list[StoredEvent]:
        query = (
            "SELECT event_id, run_id, event_type, payload_jsonb, event_ts, source, "
            "legacy_db_path, legacy_event_id, payload_hash "
            "FROM ledger_events"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if event_types:
            clauses.append("event_type = ANY(%s)")
            params.append(list(event_types))
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_ts ASC, created_at ASC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            StoredEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                event_type=row["event_type"],
                payload=dict(row["payload_jsonb"] or {}),
                timestamp=row["event_ts"],
                source=row["source"],
                legacy_db_path=row["legacy_db_path"],
                legacy_event_id=row["legacy_event_id"],
                payload_hash=row["payload_hash"],
            )
            for row in rows
        ]

    def write_telemetry_snapshot(
        self, snapshot: TelemetrySnapshotRecord
    ) -> TelemetrySnapshotRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry_snapshots
                (snapshot_id, run_id, metrics_jsonb, snapshot_ts)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    metrics_jsonb = excluded.metrics_jsonb,
                    snapshot_ts = excluded.snapshot_ts,
                    created_at = now()
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    Jsonb(snapshot.metrics),
                    snapshot.timestamp,
                ),
            )
            conn.commit()
        return snapshot

    def list_telemetry_snapshots(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[TelemetrySnapshotRecord]:
        query = (
            "SELECT snapshot_id, run_id, metrics_jsonb, snapshot_ts "
            "FROM telemetry_snapshots"
        )
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id = %s"
            params.append(run_id)
        query += " ORDER BY snapshot_ts ASC, created_at ASC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            TelemetrySnapshotRecord(
                snapshot_id=row["snapshot_id"],
                run_id=row["run_id"],
                metrics=dict(row["metrics_jsonb"] or {}),
                timestamp=row["snapshot_ts"],
            )
            for row in rows
        ]

    def append_reasoning_trace(
        self, trace: ReasoningTraceRecord
    ) -> ReasoningTraceRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reasoning_traces
                (trace_id, run_id, step_index, family, status, detail_jsonb, trace_ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(trace_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    step_index = excluded.step_index,
                    family = excluded.family,
                    status = excluded.status,
                    detail_jsonb = excluded.detail_jsonb,
                    trace_ts = excluded.trace_ts,
                    created_at = now()
                """,
                (
                    trace.trace_id,
                    trace.run_id,
                    trace.step_index,
                    trace.family,
                    trace.status,
                    Jsonb(trace.detail),
                    trace.timestamp,
                ),
            )
            conn.commit()
        return trace

    def list_reasoning_traces(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[ReasoningTraceRecord]:
        query = (
            "SELECT trace_id, run_id, step_index, family, status, detail_jsonb, trace_ts "
            "FROM reasoning_traces"
        )
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id = %s"
            params.append(run_id)
        query += " ORDER BY trace_ts ASC, step_index ASC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            ReasoningTraceRecord(
                trace_id=row["trace_id"],
                run_id=row["run_id"],
                step_index=row["step_index"],
                family=row["family"],
                status=row["status"],
                detail=dict(row["detail_jsonb"] or {}),
                timestamp=row["trace_ts"],
            )
            for row in rows
        ]

    def register_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO artifacts
                (artifact_id, run_id, kind, rel_path, abs_path, sha256, size_bytes,
                 mime_type, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    kind = excluded.kind,
                    rel_path = excluded.rel_path,
                    abs_path = excluded.abs_path,
                    sha256 = excluded.sha256,
                    size_bytes = excluded.size_bytes,
                    mime_type = excluded.mime_type,
                    metadata_jsonb = excluded.metadata_jsonb,
                    created_at = excluded.created_at
                """,
                (
                    artifact.artifact_id,
                    artifact.run_id,
                    artifact.kind,
                    artifact.rel_path,
                    artifact.abs_path,
                    artifact.sha256,
                    artifact.size_bytes,
                    artifact.mime_type,
                    Jsonb(artifact.metadata),
                    artifact.created_at,
                ),
            )
            conn.commit()
        return artifact

    def list_artifacts(
        self,
        *,
        run_id: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[ArtifactRecord]:
        query = (
            "SELECT artifact_id, run_id, kind, rel_path, abs_path, sha256, "
            "size_bytes, mime_type, metadata_jsonb, created_at FROM artifacts"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if kind:
            clauses.append("kind = %s")
            params.append(kind)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            ArtifactRecord(
                artifact_id=row["artifact_id"],
                run_id=row["run_id"],
                kind=row["kind"],
                rel_path=row["rel_path"],
                abs_path=row["abs_path"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                mime_type=row["mime_type"],
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def upsert_session_bridge(
        self, record: SessionBridgeRecord
    ) -> SessionBridgeRecord:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions
                (session_id, episode_id, channel, metadata_jsonb, timestamp)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(session_id) DO UPDATE SET
                    episode_id = excluded.episode_id,
                    channel = excluded.channel,
                    metadata_jsonb = excluded.metadata_jsonb,
                    timestamp = excluded.timestamp,
                    updated_at = now()
                """,
                (
                    record.session_id,
                    record.episode_id,
                    record.channel,
                    Jsonb(record.metadata),
                    record.timestamp,
                ),
            )
            conn.commit()
        return record

    def get_session_bridge(self, session_id: str) -> SessionBridgeRecord | None:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, episode_id, channel, metadata_jsonb, timestamp
                FROM sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return SessionBridgeRecord(
            session_id=row["session_id"],
            episode_id=row["episode_id"],
            channel=row["channel"],
            metadata=dict(row["metadata_jsonb"] or {}),
            timestamp=row["timestamp"],
        )

    def write_reality_assessment(
        self, assessment: RealityAssessmentRecord
    ) -> RealityAssessmentRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reality_assessments
                (assessment_id, run_id, bench_run_id, episode_id, closure_passed,
                 continuity_score, trace_integrity, collapse_detected, details_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(assessment_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    bench_run_id = excluded.bench_run_id,
                    episode_id = excluded.episode_id,
                    closure_passed = excluded.closure_passed,
                    continuity_score = excluded.continuity_score,
                    trace_integrity = excluded.trace_integrity,
                    collapse_detected = excluded.collapse_detected,
                    details_jsonb = excluded.details_jsonb,
                    created_at = excluded.created_at
                """,
                (
                    assessment.assessment_id,
                    assessment.run_id,
                    assessment.bench_run_id,
                    assessment.episode_id,
                    assessment.closure_passed,
                    assessment.continuity_score,
                    assessment.trace_integrity,
                    assessment.collapse_detected,
                    Jsonb(assessment.details),
                    assessment.created_at,
                ),
            )
            conn.commit()
        return assessment

    def list_reality_assessments(
        self,
        *,
        run_id: str | None = None,
        bench_run_id: str | None = None,
        limit: int = 200,
    ) -> list[RealityAssessmentRecord]:
        query = (
            "SELECT assessment_id, run_id, bench_run_id, episode_id, closure_passed, "
            "continuity_score, trace_integrity, collapse_detected, details_jsonb, created_at "
            "FROM reality_assessments"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if bench_run_id:
            clauses.append("bench_run_id = %s")
            params.append(bench_run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            RealityAssessmentRecord(
                assessment_id=row["assessment_id"],
                run_id=row["run_id"],
                bench_run_id=row["bench_run_id"],
                episode_id=row["episode_id"],
                closure_passed=bool(row["closure_passed"]),
                continuity_score=float(row["continuity_score"]),
                trace_integrity=bool(row["trace_integrity"]),
                collapse_detected=bool(row["collapse_detected"]),
                details=dict(row["details_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_reality_bench_run(
        self, bench_run: RealityBenchRunRecord
    ) -> RealityBenchRunRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reality_bench_runs
                (bench_run_id, run_id, total_episodes, closure_rate, continuity_mean,
                 collapse_count, gate_profile, passed, summary_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(bench_run_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    total_episodes = excluded.total_episodes,
                    closure_rate = excluded.closure_rate,
                    continuity_mean = excluded.continuity_mean,
                    collapse_count = excluded.collapse_count,
                    gate_profile = excluded.gate_profile,
                    passed = excluded.passed,
                    summary_jsonb = excluded.summary_jsonb,
                    created_at = excluded.created_at
                """,
                (
                    bench_run.bench_run_id,
                    bench_run.run_id,
                    bench_run.total_episodes,
                    bench_run.closure_rate,
                    bench_run.continuity_mean,
                    bench_run.collapse_count,
                    bench_run.gate_profile,
                    bench_run.passed,
                    Jsonb(bench_run.summary),
                    bench_run.created_at,
                ),
            )
            conn.commit()
        return bench_run

    def list_reality_bench_runs(
        self, *, run_id: str | None = None, limit: int = 50
    ) -> list[RealityBenchRunRecord]:
        query = (
            "SELECT bench_run_id, run_id, total_episodes, closure_rate, continuity_mean, "
            "collapse_count, gate_profile, passed, summary_jsonb, created_at "
            "FROM reality_bench_runs"
        )
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id = %s"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            RealityBenchRunRecord(
                bench_run_id=row["bench_run_id"],
                run_id=row["run_id"],
                total_episodes=int(row["total_episodes"]),
                closure_rate=float(row["closure_rate"]),
                continuity_mean=float(row["continuity_mean"]),
                collapse_count=int(row["collapse_count"]),
                gate_profile=row["gate_profile"],
                passed=bool(row["passed"]),
                summary=dict(row["summary_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_episode_certificate(
        self, certificate: EpisodeCertificateRecord
    ) -> EpisodeCertificateRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO episode_certificates
                (certificate_id, episode_id, run_id, trace_id, smg_artifacts_jsonb,
                 lotf_artifacts_jsonb, world_artifacts_jsonb, continuity_score, ioc_proxy,
                 risk_score, verdict, rollback_ready, promotion_candidate, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(certificate_id) DO UPDATE SET
                    episode_id = excluded.episode_id,
                    run_id = excluded.run_id,
                    trace_id = excluded.trace_id,
                    smg_artifacts_jsonb = excluded.smg_artifacts_jsonb,
                    lotf_artifacts_jsonb = excluded.lotf_artifacts_jsonb,
                    world_artifacts_jsonb = excluded.world_artifacts_jsonb,
                    continuity_score = excluded.continuity_score,
                    ioc_proxy = excluded.ioc_proxy,
                    risk_score = excluded.risk_score,
                    verdict = excluded.verdict,
                    rollback_ready = excluded.rollback_ready,
                    promotion_candidate = excluded.promotion_candidate,
                    metadata_jsonb = excluded.metadata_jsonb,
                    created_at = excluded.created_at
                """,
                (
                    certificate.certificate_id,
                    certificate.episode_id,
                    certificate.run_id,
                    certificate.trace_id,
                    Jsonb(certificate.smg_artifacts),
                    Jsonb(certificate.lotf_artifacts),
                    Jsonb(certificate.world_artifacts),
                    certificate.continuity_score,
                    certificate.ioc_proxy,
                    certificate.risk_score,
                    certificate.verdict,
                    certificate.rollback_ready,
                    certificate.promotion_candidate,
                    Jsonb(certificate.metadata),
                    certificate.created_at,
                ),
            )
            conn.commit()
        return certificate

    def get_episode_certificate(
        self, *, certificate_id: str | None = None, episode_id: str | None = None
    ) -> EpisodeCertificateRecord | None:
        if not certificate_id and not episode_id:
            raise ValueError("certificate_id o episode_id es obligatorio")
        query = (
            "SELECT certificate_id, episode_id, run_id, trace_id, smg_artifacts_jsonb, "
            "lotf_artifacts_jsonb, world_artifacts_jsonb, continuity_score, ioc_proxy, "
            "risk_score, verdict, rollback_ready, promotion_candidate, metadata_jsonb, created_at "
            "FROM episode_certificates"
        )
        params: list[Any] = []
        if certificate_id:
            query += " WHERE certificate_id = %s"
            params.append(certificate_id)
        elif episode_id:
            query += " WHERE episode_id = %s"
            params.append(episode_id)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        if not row:
            return None
        return EpisodeCertificateRecord(
            certificate_id=row["certificate_id"],
            episode_id=row["episode_id"],
            run_id=row["run_id"],
            trace_id=row["trace_id"],
            smg_artifacts=dict(row["smg_artifacts_jsonb"] or {}),
            lotf_artifacts=dict(row["lotf_artifacts_jsonb"] or {}),
            world_artifacts=dict(row["world_artifacts_jsonb"] or {}),
            continuity_score=float(row["continuity_score"]),
            ioc_proxy=float(row["ioc_proxy"]),
            risk_score=float(row["risk_score"]),
            verdict=row["verdict"],
            rollback_ready=bool(row["rollback_ready"]),
            promotion_candidate=bool(row["promotion_candidate"]),
            metadata=dict(row["metadata_jsonb"] or {}),
            created_at=row["created_at"],
        )

    def list_episode_certificates(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[EpisodeCertificateRecord]:
        query = (
            "SELECT certificate_id, episode_id, run_id, trace_id, smg_artifacts_jsonb, "
            "lotf_artifacts_jsonb, world_artifacts_jsonb, continuity_score, ioc_proxy, "
            "risk_score, verdict, rollback_ready, promotion_candidate, metadata_jsonb, created_at "
            "FROM episode_certificates"
        )
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id = %s"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            EpisodeCertificateRecord(
                certificate_id=row["certificate_id"],
                episode_id=row["episode_id"],
                run_id=row["run_id"],
                trace_id=row["trace_id"],
                smg_artifacts=dict(row["smg_artifacts_jsonb"] or {}),
                lotf_artifacts=dict(row["lotf_artifacts_jsonb"] or {}),
                world_artifacts=dict(row["world_artifacts_jsonb"] or {}),
                continuity_score=float(row["continuity_score"]),
                ioc_proxy=float(row["ioc_proxy"]),
                risk_score=float(row["risk_score"]),
                verdict=row["verdict"],
                rollback_ready=bool(row["rollback_ready"]),
                promotion_candidate=bool(row["promotion_candidate"]),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_promotion_decision(
        self, decision: PromotionDecisionRecord
    ) -> PromotionDecisionRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO promotion_decisions
                (decision_id, episode_id, run_id, certificate_id, verdict, reason,
                 rollback_ready, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(decision_id) DO UPDATE SET
                    episode_id = excluded.episode_id,
                    run_id = excluded.run_id,
                    certificate_id = excluded.certificate_id,
                    verdict = excluded.verdict,
                    reason = excluded.reason,
                    rollback_ready = excluded.rollback_ready,
                    metadata_jsonb = excluded.metadata_jsonb,
                    created_at = excluded.created_at
                """,
                (
                    decision.decision_id,
                    decision.episode_id,
                    decision.run_id,
                    decision.certificate_id,
                    decision.verdict,
                    decision.reason,
                    decision.rollback_ready,
                    Jsonb(decision.metadata),
                    decision.created_at,
                ),
            )
            conn.commit()
        return decision

    def list_promotion_decisions(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[PromotionDecisionRecord]:
        query = (
            "SELECT decision_id, episode_id, run_id, certificate_id, verdict, reason, "
            "rollback_ready, metadata_jsonb, created_at FROM promotion_decisions"
        )
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id = %s"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            PromotionDecisionRecord(
                decision_id=row["decision_id"],
                episode_id=row["episode_id"],
                run_id=row["run_id"],
                certificate_id=row["certificate_id"],
                verdict=row["verdict"],
                reason=row["reason"],
                rollback_ready=bool(row["rollback_ready"]),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_memory_record(self, memory: MemoryRecord) -> MemoryRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_records
                (memory_id, run_id, episode_id, scale, structure_jsonb, ttl_seconds,
                 no_interference, certificate_id, ioc_proxy, support_count, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(memory_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    episode_id = excluded.episode_id,
                    scale = excluded.scale,
                    structure_jsonb = excluded.structure_jsonb,
                    ttl_seconds = excluded.ttl_seconds,
                    no_interference = excluded.no_interference,
                    certificate_id = excluded.certificate_id,
                    ioc_proxy = excluded.ioc_proxy,
                    support_count = excluded.support_count,
                    metadata_jsonb = excluded.metadata_jsonb,
                    created_at = excluded.created_at
                """,
                (
                    memory.memory_id,
                    memory.run_id,
                    memory.episode_id,
                    memory.scale,
                    Jsonb(memory.structure_json),
                    memory.ttl_seconds,
                    memory.no_interference,
                    memory.certificate_id,
                    memory.ioc_proxy,
                    memory.support_count,
                    Jsonb(memory.metadata),
                    memory.created_at,
                ),
            )
            conn.commit()
        return memory

    def retrieve_memory_records(
        self,
        *,
        run_id: str | None = None,
        scales: Sequence[str] | None = None,
        min_ioc_proxy: float | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        query = (
            "SELECT memory_id, run_id, episode_id, scale, structure_jsonb, ttl_seconds, "
            "no_interference, certificate_id, ioc_proxy, support_count, metadata_jsonb, created_at "
            "FROM memory_records"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if scales:
            clauses.append("scale = ANY(%s)")
            params.append(list(scales))
        if min_ioc_proxy is not None:
            clauses.append("ioc_proxy >= %s")
            params.append(min_ioc_proxy)
        # B2 - Aplicar TTL en lectura: excluir memorias expiradas.
        clauses.append(_MEMORY_NOT_EXPIRED_SQL)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            MemoryRecord(
                memory_id=row["memory_id"],
                run_id=row["run_id"],
                episode_id=row["episode_id"],
                scale=row["scale"],
                structure_json=dict(row["structure_jsonb"] or {}),
                ttl_seconds=row["ttl_seconds"],
                no_interference=bool(row["no_interference"]),
                certificate_id=row["certificate_id"],
                ioc_proxy=float(row["ioc_proxy"]) if row["ioc_proxy"] is not None else None,
                support_count=int(row["support_count"]),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def purge_expired_memory_records(self) -> int:
        """B2 - Borra las memorias expiradas (now > created_at + ttl_seconds).

        Devuelve la cantidad de filas borradas. ttl_seconds NULL nunca expira.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM memory_records WHERE {_MEMORY_EXPIRED_SQL}"
            )
            deleted = cur.rowcount
            conn.commit()
        return int(deleted)

    def write_transfer_assessment(
        self, assessment: TransferAssessmentRecord,
    ) -> TransferAssessmentRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transfer_assessments
                (assessment_id, run_id, episode_id, source_scenario, target_scenario,
                 compatibility_class, transfer_verdict, memory_purity_score,
                 transition_stability_score, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (assessment_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    episode_id = EXCLUDED.episode_id,
                    source_scenario = EXCLUDED.source_scenario,
                    target_scenario = EXCLUDED.target_scenario,
                    compatibility_class = EXCLUDED.compatibility_class,
                    transfer_verdict = EXCLUDED.transfer_verdict,
                    memory_purity_score = EXCLUDED.memory_purity_score,
                    transition_stability_score = EXCLUDED.transition_stability_score,
                    metadata_jsonb = EXCLUDED.metadata_jsonb
                """,
                (
                    assessment.assessment_id,
                    assessment.run_id,
                    assessment.episode_id,
                    assessment.source_scenario,
                    assessment.target_scenario,
                    assessment.compatibility_class,
                    assessment.transfer_verdict,
                    assessment.memory_purity_score,
                    assessment.transition_stability_score,
                    Jsonb(assessment.metadata),
                    assessment.created_at,
                ),
            )
            conn.commit()
        return assessment

    def list_transfer_assessments(
        self,
        *,
        run_id: str | None = None,
        episode_id: str | None = None,
        limit: int = 200,
    ) -> list[TransferAssessmentRecord]:
        query = (
            "SELECT assessment_id, run_id, episode_id, source_scenario, target_scenario, "
            "compatibility_class, transfer_verdict, memory_purity_score, "
            "transition_stability_score, metadata_jsonb, created_at "
            "FROM transfer_assessments"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if episode_id:
            clauses.append("episode_id = %s")
            params.append(episode_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            TransferAssessmentRecord(
                assessment_id=row["assessment_id"],
                run_id=row["run_id"],
                episode_id=row["episode_id"],
                source_scenario=row["source_scenario"],
                target_scenario=row["target_scenario"],
                compatibility_class=row["compatibility_class"],
                transfer_verdict=row["transfer_verdict"],
                memory_purity_score=float(row["memory_purity_score"]),
                transition_stability_score=float(row["transition_stability_score"]),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_organism_snapshot(
        self, snapshot: OrganismSnapshotRecord
    ) -> OrganismSnapshotRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO organism_snapshots
                (snapshot_id, run_id, episode_id, trajectory_id, regime, snapshot_jsonb, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    episode_id = EXCLUDED.episode_id,
                    trajectory_id = EXCLUDED.trajectory_id,
                    regime = EXCLUDED.regime,
                    snapshot_jsonb = EXCLUDED.snapshot_jsonb,
                    metadata_jsonb = EXCLUDED.metadata_jsonb,
                    created_at = EXCLUDED.created_at
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    snapshot.episode_id,
                    snapshot.trajectory_id,
                    snapshot.regime,
                    Jsonb(snapshot.snapshot_json),
                    Jsonb(snapshot.metadata),
                    snapshot.created_at,
                ),
            )
            conn.commit()
        return snapshot

    def list_organism_snapshots(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[OrganismSnapshotRecord]:
        query = (
            "SELECT snapshot_id, run_id, episode_id, trajectory_id, regime, snapshot_jsonb, metadata_jsonb, created_at "
            "FROM organism_snapshots"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = %s")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            OrganismSnapshotRecord(
                snapshot_id=row["snapshot_id"],
                run_id=row["run_id"],
                episode_id=row["episode_id"],
                trajectory_id=row["trajectory_id"],
                regime=row["regime"],
                snapshot_json=dict(row["snapshot_jsonb"] or {}),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_trajectory_window(
        self, window: TrajectoryWindowRecord
    ) -> TrajectoryWindowRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trajectory_windows
                (window_id, run_id, trajectory_id, start_episode, end_episode, snapshots_jsonb, digest_jsonb, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (window_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    trajectory_id = EXCLUDED.trajectory_id,
                    start_episode = EXCLUDED.start_episode,
                    end_episode = EXCLUDED.end_episode,
                    snapshots_jsonb = EXCLUDED.snapshots_jsonb,
                    digest_jsonb = EXCLUDED.digest_jsonb,
                    metadata_jsonb = EXCLUDED.metadata_jsonb,
                    created_at = EXCLUDED.created_at
                """,
                (
                    window.window_id,
                    window.run_id,
                    window.trajectory_id,
                    window.start_episode,
                    window.end_episode,
                    Jsonb(window.snapshots_json),
                    Jsonb(window.digest_json),
                    Jsonb(window.metadata),
                    window.created_at,
                ),
            )
            conn.commit()
        return window

    def list_trajectory_windows(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryWindowRecord]:
        query = (
            "SELECT window_id, run_id, trajectory_id, start_episode, end_episode, snapshots_jsonb, digest_jsonb, metadata_jsonb, created_at "
            "FROM trajectory_windows"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = %s")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            TrajectoryWindowRecord(
                window_id=row["window_id"],
                run_id=row["run_id"],
                trajectory_id=row["trajectory_id"],
                start_episode=int(row["start_episode"]),
                end_episode=int(row["end_episode"]),
                snapshots_json=dict(row["snapshots_jsonb"] or {}),
                digest_json=dict(row["digest_jsonb"] or {}),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_trajectory_flow_report(
        self, report: TrajectoryFlowReportRecord
    ) -> TrajectoryFlowReportRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trajectory_flow_reports
                (report_id, run_id, trajectory_id, window_id, flow_validity, erosion, phase_drift, rollback_obligation, report_jsonb, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (report_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    trajectory_id = EXCLUDED.trajectory_id,
                    window_id = EXCLUDED.window_id,
                    flow_validity = EXCLUDED.flow_validity,
                    erosion = EXCLUDED.erosion,
                    phase_drift = EXCLUDED.phase_drift,
                    rollback_obligation = EXCLUDED.rollback_obligation,
                    report_jsonb = EXCLUDED.report_jsonb,
                    metadata_jsonb = EXCLUDED.metadata_jsonb,
                    created_at = EXCLUDED.created_at
                """,
                (
                    report.report_id,
                    report.run_id,
                    report.trajectory_id,
                    report.window_id,
                    report.flow_validity,
                    report.erosion,
                    report.phase_drift,
                    report.rollback_obligation,
                    Jsonb(report.report_json),
                    Jsonb(report.metadata),
                    report.created_at,
                ),
            )
            conn.commit()
        return report

    def list_trajectory_flow_reports(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[TrajectoryFlowReportRecord]:
        query = (
            "SELECT report_id, run_id, trajectory_id, window_id, flow_validity, erosion, phase_drift, rollback_obligation, report_jsonb, metadata_jsonb, created_at "
            "FROM trajectory_flow_reports"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = %s")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            TrajectoryFlowReportRecord(
                report_id=row["report_id"],
                run_id=row["run_id"],
                trajectory_id=row["trajectory_id"],
                window_id=row["window_id"],
                flow_validity=bool(row["flow_validity"]),
                erosion=float(row["erosion"]),
                phase_drift=float(row["phase_drift"]),
                rollback_obligation=bool(row["rollback_obligation"]),
                report_json=dict(row["report_jsonb"] or {}),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_renormalization_event(
        self, event: RenormalizationEventRecord
    ) -> RenormalizationEventRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO renormalization_events
                (event_id, run_id, trajectory_id, source_regime, target_regime, residual_error, transport_uncertainty, expected_recovery_cost, map_jsonb, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    trajectory_id = EXCLUDED.trajectory_id,
                    source_regime = EXCLUDED.source_regime,
                    target_regime = EXCLUDED.target_regime,
                    residual_error = EXCLUDED.residual_error,
                    transport_uncertainty = EXCLUDED.transport_uncertainty,
                    expected_recovery_cost = EXCLUDED.expected_recovery_cost,
                    map_jsonb = EXCLUDED.map_jsonb,
                    metadata_jsonb = EXCLUDED.metadata_jsonb,
                    created_at = EXCLUDED.created_at
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.trajectory_id,
                    event.source_regime,
                    event.target_regime,
                    event.residual_error,
                    event.transport_uncertainty,
                    event.expected_recovery_cost,
                    Jsonb(event.map_json),
                    Jsonb(event.metadata),
                    event.created_at,
                ),
            )
            conn.commit()
        return event

    def list_renormalization_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        limit: int = 200,
    ) -> list[RenormalizationEventRecord]:
        query = (
            "SELECT event_id, run_id, trajectory_id, source_regime, target_regime, residual_error, transport_uncertainty, expected_recovery_cost, map_jsonb, metadata_jsonb, created_at "
            "FROM renormalization_events"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = %s")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            RenormalizationEventRecord(
                event_id=row["event_id"],
                run_id=row["run_id"],
                trajectory_id=row["trajectory_id"],
                source_regime=row["source_regime"],
                target_regime=row["target_regime"],
                residual_error=float(row["residual_error"]),
                transport_uncertainty=float(row["transport_uncertainty"]),
                expected_recovery_cost=float(row["expected_recovery_cost"]),
                map_json=dict(row["map_jsonb"] or {}),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_constitutional_risk_state(
        self, risk_state: ConstitutionalRiskStateRecord
    ) -> ConstitutionalRiskStateRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO constitutional_risk_states
                (state_id, run_id, trajectory_id, scope_type, scope_key, risk_score, risk_jsonb, prev_state_id, step_index, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (state_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    trajectory_id = EXCLUDED.trajectory_id,
                    scope_type = EXCLUDED.scope_type,
                    scope_key = EXCLUDED.scope_key,
                    risk_score = EXCLUDED.risk_score,
                    risk_jsonb = EXCLUDED.risk_jsonb,
                    prev_state_id = EXCLUDED.prev_state_id,
                    step_index = EXCLUDED.step_index,
                    metadata_jsonb = EXCLUDED.metadata_jsonb,
                    created_at = EXCLUDED.created_at
                """,
                (
                    risk_state.state_id,
                    risk_state.run_id,
                    risk_state.trajectory_id,
                    risk_state.scope_type,
                    risk_state.scope_key,
                    risk_state.risk_score,
                    Jsonb(risk_state.risk_json),
                    risk_state.prev_state_id,
                    risk_state.step_index,
                    Jsonb(risk_state.metadata),
                    risk_state.created_at,
                ),
            )
            conn.commit()
        return risk_state

    def list_constitutional_risk_states(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[ConstitutionalRiskStateRecord]:
        query = (
            "SELECT state_id, run_id, trajectory_id, scope_type, scope_key, risk_score, risk_jsonb, prev_state_id, step_index, metadata_jsonb, created_at "
            "FROM constitutional_risk_states"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = %s")
            params.append(trajectory_id)
        if scope_type:
            clauses.append("scope_type = %s")
            params.append(scope_type)
        if scope_key:
            clauses.append("scope_key = %s")
            params.append(scope_key)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY step_index DESC, created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            ConstitutionalRiskStateRecord(
                state_id=row["state_id"],
                run_id=row["run_id"],
                trajectory_id=row["trajectory_id"],
                scope_type=row["scope_type"],
                scope_key=row["scope_key"],
                risk_score=float(row["risk_score"]),
                risk_json=dict(row["risk_jsonb"] or {}),
                prev_state_id=row["prev_state_id"],
                step_index=int(row["step_index"] or 0),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def write_failure_atlas_event(
        self, event: FailureAtlasEventRecord
    ) -> FailureAtlasEventRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO failure_atlas_events
                (event_id, run_id, trajectory_id, scope_type, scope_key, failure_class, severity, reversible, recovery_protocol, signature_jsonb, metadata_jsonb, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    trajectory_id = EXCLUDED.trajectory_id,
                    scope_type = EXCLUDED.scope_type,
                    scope_key = EXCLUDED.scope_key,
                    failure_class = EXCLUDED.failure_class,
                    severity = EXCLUDED.severity,
                    reversible = EXCLUDED.reversible,
                    recovery_protocol = EXCLUDED.recovery_protocol,
                    signature_jsonb = EXCLUDED.signature_jsonb,
                    metadata_jsonb = EXCLUDED.metadata_jsonb,
                    created_at = EXCLUDED.created_at
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.trajectory_id,
                    event.scope_type,
                    event.scope_key,
                    event.failure_class,
                    event.severity,
                    event.reversible,
                    event.recovery_protocol,
                    Jsonb(event.signature_json),
                    Jsonb(event.metadata),
                    event.created_at,
                ),
            )
            conn.commit()
        return event

    def list_failure_atlas_events(
        self,
        *,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        scope_type: str | None = None,
        scope_key: str | None = None,
        limit: int = 200,
    ) -> list[FailureAtlasEventRecord]:
        query = (
            "SELECT event_id, run_id, trajectory_id, scope_type, scope_key, failure_class, severity, reversible, recovery_protocol, signature_jsonb, metadata_jsonb, created_at "
            "FROM failure_atlas_events"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = %s")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = %s")
            params.append(trajectory_id)
        if scope_type:
            clauses.append("scope_type = %s")
            params.append(scope_type)
        if scope_key:
            clauses.append("scope_key = %s")
            params.append(scope_key)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            FailureAtlasEventRecord(
                event_id=row["event_id"],
                run_id=row["run_id"],
                trajectory_id=row["trajectory_id"],
                scope_type=row["scope_type"],
                scope_key=row["scope_key"],
                failure_class=row["failure_class"],
                severity=row["severity"],
                reversible=bool(row["reversible"]),
                recovery_protocol=row["recovery_protocol"],
                signature_json=dict(row["signature_jsonb"] or {}),
                metadata=dict(row["metadata_jsonb"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def close(self) -> None:
        # Conexion por operacion; no hay pool persistente.
        return None
