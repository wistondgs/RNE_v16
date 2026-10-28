"""Backend SQLite para storage RNFE."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Sequence

from runtime.core.event_log_sqlite import (
    EventLogSQLite,
    configure_sqlite_connection,
)

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


# B2 - Edad de una fila de memory_records en segundos (now - created_at) usando
# el reloj UTC de SQLite. strftime('%s', ...) parsea el ISO-8601 UTC de created_at.
_MEMORY_AGE_SECONDS_SQL = (
    "(CAST(strftime('%s', 'now') AS INTEGER) "
    "- CAST(strftime('%s', created_at) AS INTEGER))"
)
# Condicion "NO expirada" para filtrar en lectura.
_MEMORY_NOT_EXPIRED_SQL = (
    "(ttl_seconds IS NULL "
    "OR strftime('%s', created_at) IS NULL "
    f"OR {_MEMORY_AGE_SECONDS_SQL} <= ttl_seconds)"
)
# Condicion "expirada" para purgar (complemento estricto de la anterior).
_MEMORY_EXPIRED_SQL = (
    "ttl_seconds IS NOT NULL "
    "AND strftime('%s', created_at) IS NOT NULL "
    f"AND {_MEMORY_AGE_SECONDS_SQL} > ttl_seconds"
)


def _safe_json_load(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {"value": data}


class SQLiteStorageBackend(StorageBackend):
    """Implementacion SQLite local/fallback con compatibilidad legacy."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ledger = EventLogSQLite(db_path)
        self._ensure_aux_schema()

    def _connect(self) -> sqlite3.Connection:
        return configure_sqlite_connection(sqlite3.connect(self.db_path))

    def _ensure_aux_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    metrics TEXT NOT NULL,
                    snapshot_ts TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reasoning_traces (
                    trace_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    step_index INTEGER NOT NULL,
                    family TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT,
                    trace_ts TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    kind TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    abs_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mime_type TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reality_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    bench_run_id TEXT,
                    episode_id TEXT NOT NULL,
                    closure_passed INTEGER NOT NULL,
                    continuity_score REAL NOT NULL,
                    trace_integrity INTEGER NOT NULL,
                    collapse_detected INTEGER NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reality_bench_runs (
                    bench_run_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    total_episodes INTEGER NOT NULL,
                    closure_rate REAL NOT NULL,
                    continuity_mean REAL NOT NULL,
                    collapse_count INTEGER NOT NULL,
                    gate_profile TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    summary TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episode_certificates (
                    certificate_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    smg_artifacts TEXT NOT NULL,
                    lotf_artifacts TEXT NOT NULL,
                    world_artifacts TEXT NOT NULL,
                    continuity_score REAL NOT NULL,
                    ioc_proxy REAL NOT NULL,
                    risk_score REAL NOT NULL,
                    verdict TEXT NOT NULL,
                    rollback_ready INTEGER NOT NULL,
                    promotion_candidate INTEGER NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS promotion_decisions (
                    decision_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    certificate_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    rollback_ready INTEGER NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    scale TEXT NOT NULL,
                    structure_json TEXT NOT NULL,
                    ttl_seconds INTEGER,
                    no_interference INTEGER NOT NULL,
                    certificate_id TEXT,
                    ioc_proxy REAL,
                    support_count INTEGER NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_telemetry_run_ts
                ON telemetry_snapshots(run_id, snapshot_ts);

                CREATE INDEX IF NOT EXISTS idx_reasoning_run_step
                ON reasoning_traces(run_id, step_index);

                CREATE INDEX IF NOT EXISTS idx_artifacts_run_kind
                ON artifacts(run_id, kind, created_at);

                CREATE INDEX IF NOT EXISTS idx_reality_assessments_run_bench
                ON reality_assessments(run_id, bench_run_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_reality_bench_runs_run
                ON reality_bench_runs(run_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_episode_certificates_run
                ON episode_certificates(run_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_promotion_decisions_run
                ON promotion_decisions(run_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_memory_records_run_scale
                ON memory_records(run_id, scale, created_at);

                CREATE TABLE IF NOT EXISTS transfer_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    source_scenario TEXT NOT NULL,
                    target_scenario TEXT NOT NULL,
                    compatibility_class TEXT NOT NULL,
                    transfer_verdict TEXT NOT NULL,
                    memory_purity_score REAL NOT NULL,
                    transition_stability_score REAL NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_transfer_assessments_run
                ON transfer_assessments(run_id, created_at);

                CREATE TABLE IF NOT EXISTS organism_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    trajectory_id TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trajectory_windows (
                    window_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    trajectory_id TEXT NOT NULL,
                    start_episode INTEGER NOT NULL,
                    end_episode INTEGER NOT NULL,
                    snapshots_json TEXT NOT NULL,
                    digest_json TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trajectory_flow_reports (
                    report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    trajectory_id TEXT NOT NULL,
                    window_id TEXT NOT NULL,
                    flow_validity INTEGER NOT NULL,
                    erosion REAL NOT NULL,
                    phase_drift REAL NOT NULL,
                    rollback_obligation INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS renormalization_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    trajectory_id TEXT NOT NULL,
                    source_regime TEXT NOT NULL,
                    target_regime TEXT NOT NULL,
                    residual_error REAL NOT NULL,
                    transport_uncertainty REAL NOT NULL,
                    expected_recovery_cost REAL NOT NULL,
                    map_json TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS constitutional_risk_states (
                    state_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    trajectory_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    risk_json TEXT NOT NULL,
                    prev_state_id TEXT,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS failure_atlas_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    trajectory_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    reversible INTEGER NOT NULL,
                    recovery_protocol TEXT NOT NULL,
                    signature_json TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_organism_snapshots_run_traj
                ON organism_snapshots(run_id, trajectory_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_trajectory_windows_run_traj
                ON trajectory_windows(run_id, trajectory_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_flow_reports_run_traj
                ON trajectory_flow_reports(run_id, trajectory_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_renorm_events_run_traj
                ON renormalization_events(run_id, trajectory_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_risk_states_run_traj_scope
                ON constitutional_risk_states(run_id, trajectory_id, scope_type, scope_key, created_at);

                CREATE INDEX IF NOT EXISTS idx_failure_atlas_run_traj_scope
                ON failure_atlas_events(run_id, trajectory_id, scope_type, scope_key, created_at);
                """
            )
            # Compatibilidad con DBs previas al chain de riesgo T5.
            risk_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(constitutional_risk_states)").fetchall()
            }
            if "prev_state_id" not in risk_cols:
                conn.execute("ALTER TABLE constitutional_risk_states ADD COLUMN prev_state_id TEXT")
            if "step_index" not in risk_cols:
                conn.execute(
                    "ALTER TABLE constitutional_risk_states ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_risk_states_run_traj_scope_step "
                "ON constitutional_risk_states(run_id, trajectory_id, scope_type, scope_key, step_index, created_at)"
            )
            conn.commit()

    def append_event(self, event: StoredEvent) -> StoredEvent:
        payload = dict(event.payload or {})
        if event.run_id and "run_id" not in payload:
            payload["run_id"] = event.run_id
        if event.source and "source" not in payload:
            payload["source"] = event.source
        with self._lock:
            self._ledger.log_event(event.event_type, payload, event.timestamp)
        return event

    def list_events(
        self,
        *,
        limit: int = 200,
        event_types: Sequence[str] | None = None,
        run_id: str | None = None,
    ) -> list[StoredEvent]:
        rows = self._ledger.get_events(
            limit=limit, event_types=list(event_types or []), run_id=run_id
        )
        events: list[StoredEvent] = []
        for row in rows:
            payload = row.get("payload")
            payload_dict = payload if isinstance(payload, dict) else {"value": payload}
            item = StoredEvent(
                event_type=row.get("event", "unknown"),
                payload=payload_dict,
                timestamp=row.get("timestamp") or "",
                run_id=payload_dict.get("run_id") or payload_dict.get("_run_id"),
                source=payload_dict.get("source"),
            )
            if run_id and item.run_id != run_id:
                continue
            events.append(item)
        return events[-limit:]

    def write_telemetry_snapshot(
        self, snapshot: TelemetrySnapshotRecord
    ) -> TelemetrySnapshotRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO telemetry_snapshots
                (snapshot_id, run_id, metrics, snapshot_ts)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    json.dumps(snapshot.metrics),
                    snapshot.timestamp,
                ),
            )
            conn.commit()
        return snapshot

    def list_telemetry_snapshots(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[TelemetrySnapshotRecord]:
        query = (
            "SELECT snapshot_id, run_id, metrics, snapshot_ts "
            "FROM telemetry_snapshots"
        )
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY snapshot_ts ASC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            TelemetrySnapshotRecord(
                snapshot_id=row[0],
                run_id=row[1],
                metrics=_safe_json_load(row[2]),
                timestamp=row[3],
            )
            for row in rows
        ]

    def append_reasoning_trace(
        self, trace: ReasoningTraceRecord
    ) -> ReasoningTraceRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reasoning_traces
                (trace_id, run_id, step_index, family, status, detail, trace_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.run_id,
                    trace.step_index,
                    trace.family,
                    trace.status,
                    json.dumps(trace.detail),
                    trace.timestamp,
                ),
            )
            conn.commit()
        return trace

    def list_reasoning_traces(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[ReasoningTraceRecord]:
        query = (
            "SELECT trace_id, run_id, step_index, family, status, detail, trace_ts "
            "FROM reasoning_traces"
        )
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY trace_ts ASC, step_index ASC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ReasoningTraceRecord(
                trace_id=row[0],
                run_id=row[1],
                step_index=row[2],
                family=row[3],
                status=row[4],
                detail=_safe_json_load(row[5]),
                timestamp=row[6],
            )
            for row in rows
        ]

    def register_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts
                (artifact_id, run_id, kind, rel_path, abs_path, sha256, size_bytes,
                 mime_type, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(artifact.metadata),
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
            "size_bytes, mime_type, metadata, created_at FROM artifacts"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ArtifactRecord(
                artifact_id=row[0],
                run_id=row[1],
                kind=row[2],
                rel_path=row[3],
                abs_path=row[4],
                sha256=row[5],
                size_bytes=row[6],
                mime_type=row[7],
                metadata=_safe_json_load(row[8]),
                created_at=row[9],
            )
            for row in rows
        ]

    def upsert_session_bridge(
        self, record: SessionBridgeRecord
    ) -> SessionBridgeRecord:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, episode_id, channel, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    episode_id=excluded.episode_id,
                    channel=excluded.channel,
                    timestamp=excluded.timestamp,
                    metadata=excluded.metadata
                """,
                (
                    record.session_id,
                    record.episode_id,
                    record.channel,
                    record.timestamp,
                    json.dumps(record.metadata),
                ),
            )
            conn.commit()
        return record

    def get_session_bridge(self, session_id: str) -> SessionBridgeRecord | None:
        """Capacidad reservada: implementada en toda la capa de storage pero SIN
        productores/consumidores en el runtime actual (B23). No remover sin
        decision de producto."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, episode_id, channel, timestamp, metadata
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return SessionBridgeRecord(
            session_id=row[0],
            episode_id=row[1],
            channel=row[2],
            timestamp=row[3],
            metadata=_safe_json_load(row[4]),
        )

    def write_reality_assessment(
        self, assessment: RealityAssessmentRecord
    ) -> RealityAssessmentRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reality_assessments
                (assessment_id, run_id, bench_run_id, episode_id, closure_passed,
                 continuity_score, trace_integrity, collapse_detected, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    assessment.run_id,
                    assessment.bench_run_id,
                    assessment.episode_id,
                    int(assessment.closure_passed),
                    assessment.continuity_score,
                    int(assessment.trace_integrity),
                    int(assessment.collapse_detected),
                    json.dumps(assessment.details),
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
            "continuity_score, trace_integrity, collapse_detected, details, created_at "
            "FROM reality_assessments"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if bench_run_id:
            clauses.append("bench_run_id = ?")
            params.append(bench_run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            RealityAssessmentRecord(
                assessment_id=row[0],
                run_id=row[1],
                bench_run_id=row[2],
                episode_id=row[3],
                closure_passed=bool(row[4]),
                continuity_score=float(row[5]),
                trace_integrity=bool(row[6]),
                collapse_detected=bool(row[7]),
                details=_safe_json_load(row[8]),
                created_at=row[9],
            )
            for row in rows
        ]

    def write_reality_bench_run(
        self, bench_run: RealityBenchRunRecord
    ) -> RealityBenchRunRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reality_bench_runs
                (bench_run_id, run_id, total_episodes, closure_rate, continuity_mean,
                 collapse_count, gate_profile, passed, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bench_run.bench_run_id,
                    bench_run.run_id,
                    bench_run.total_episodes,
                    bench_run.closure_rate,
                    bench_run.continuity_mean,
                    bench_run.collapse_count,
                    bench_run.gate_profile,
                    int(bench_run.passed),
                    json.dumps(bench_run.summary),
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
            "collapse_count, gate_profile, passed, summary, created_at FROM reality_bench_runs"
        )
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            RealityBenchRunRecord(
                bench_run_id=row[0],
                run_id=row[1],
                total_episodes=int(row[2]),
                closure_rate=float(row[3]),
                continuity_mean=float(row[4]),
                collapse_count=int(row[5]),
                gate_profile=row[6],
                passed=bool(row[7]),
                summary=_safe_json_load(row[8]),
                created_at=row[9],
            )
            for row in rows
        ]

    def write_episode_certificate(
        self, certificate: EpisodeCertificateRecord
    ) -> EpisodeCertificateRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO episode_certificates
                (certificate_id, episode_id, run_id, trace_id, smg_artifacts, lotf_artifacts,
                 world_artifacts, continuity_score, ioc_proxy, risk_score, verdict, rollback_ready,
                 promotion_candidate, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    certificate.certificate_id,
                    certificate.episode_id,
                    certificate.run_id,
                    certificate.trace_id,
                    json.dumps(certificate.smg_artifacts),
                    json.dumps(certificate.lotf_artifacts),
                    json.dumps(certificate.world_artifacts),
                    certificate.continuity_score,
                    certificate.ioc_proxy,
                    certificate.risk_score,
                    certificate.verdict,
                    int(certificate.rollback_ready),
                    int(certificate.promotion_candidate),
                    json.dumps(certificate.metadata),
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
            "SELECT certificate_id, episode_id, run_id, trace_id, smg_artifacts, "
            "lotf_artifacts, world_artifacts, continuity_score, ioc_proxy, risk_score, "
            "verdict, rollback_ready, promotion_candidate, metadata, created_at "
            "FROM episode_certificates"
        )
        params: list[object] = []
        if certificate_id:
            query += " WHERE certificate_id = ?"
            params.append(certificate_id)
        elif episode_id:
            query += " WHERE episode_id = ?"
            params.append(episode_id)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return EpisodeCertificateRecord(
            certificate_id=row[0],
            episode_id=row[1],
            run_id=row[2],
            trace_id=row[3],
            smg_artifacts=_safe_json_load(row[4]),
            lotf_artifacts=_safe_json_load(row[5]),
            world_artifacts=_safe_json_load(row[6]),
            continuity_score=float(row[7]),
            ioc_proxy=float(row[8]),
            risk_score=float(row[9]),
            verdict=row[10],
            rollback_ready=bool(row[11]),
            promotion_candidate=bool(row[12]),
            metadata=_safe_json_load(row[13]),
            created_at=row[14],
        )

    def list_episode_certificates(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[EpisodeCertificateRecord]:
        query = (
            "SELECT certificate_id, episode_id, run_id, trace_id, smg_artifacts, "
            "lotf_artifacts, world_artifacts, continuity_score, ioc_proxy, risk_score, "
            "verdict, rollback_ready, promotion_candidate, metadata, created_at "
            "FROM episode_certificates"
        )
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            EpisodeCertificateRecord(
                certificate_id=row[0],
                episode_id=row[1],
                run_id=row[2],
                trace_id=row[3],
                smg_artifacts=_safe_json_load(row[4]),
                lotf_artifacts=_safe_json_load(row[5]),
                world_artifacts=_safe_json_load(row[6]),
                continuity_score=float(row[7]),
                ioc_proxy=float(row[8]),
                risk_score=float(row[9]),
                verdict=row[10],
                rollback_ready=bool(row[11]),
                promotion_candidate=bool(row[12]),
                metadata=_safe_json_load(row[13]),
                created_at=row[14],
            )
            for row in rows
        ]

    def write_promotion_decision(
        self, decision: PromotionDecisionRecord
    ) -> PromotionDecisionRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO promotion_decisions
                (decision_id, episode_id, run_id, certificate_id, verdict, reason,
                 rollback_ready, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.episode_id,
                    decision.run_id,
                    decision.certificate_id,
                    decision.verdict,
                    decision.reason,
                    int(decision.rollback_ready),
                    json.dumps(decision.metadata),
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
            "rollback_ready, metadata, created_at FROM promotion_decisions"
        )
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            PromotionDecisionRecord(
                decision_id=row[0],
                episode_id=row[1],
                run_id=row[2],
                certificate_id=row[3],
                verdict=row[4],
                reason=row[5],
                rollback_ready=bool(row[6]),
                metadata=_safe_json_load(row[7]),
                created_at=row[8],
            )
            for row in rows
        ]

    def write_memory_record(self, memory: MemoryRecord) -> MemoryRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_records
                (memory_id, run_id, episode_id, scale, structure_json, ttl_seconds,
                 no_interference, certificate_id, ioc_proxy, support_count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id,
                    memory.run_id,
                    memory.episode_id,
                    memory.scale,
                    json.dumps(memory.structure_json),
                    memory.ttl_seconds,
                    int(memory.no_interference),
                    memory.certificate_id,
                    memory.ioc_proxy,
                    memory.support_count,
                    json.dumps(memory.metadata),
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
            "SELECT memory_id, run_id, episode_id, scale, structure_json, ttl_seconds, "
            "no_interference, certificate_id, ioc_proxy, support_count, metadata, created_at "
            "FROM memory_records"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if scales:
            placeholders = ",".join(["?"] * len(scales))
            clauses.append(f"scale IN ({placeholders})")
            params.extend(scales)
        if min_ioc_proxy is not None:
            clauses.append("ioc_proxy >= ?")
            params.append(min_ioc_proxy)
        # B2 - Aplicar TTL en lectura: excluir memorias expiradas. Una memoria
        # expira cuando now > created_at + ttl_seconds. ttl_seconds NULL = sin
        # expiracion; un created_at no parseable se trata como sin expiracion
        # (defensivo, no deberia ocurrir: siempre lo escribe utc_now_iso()).
        clauses.append(_MEMORY_NOT_EXPIRED_SQL)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            MemoryRecord(
                memory_id=row[0],
                run_id=row[1],
                episode_id=row[2],
                scale=row[3],
                structure_json=_safe_json_load(row[4]),
                ttl_seconds=row[5],
                no_interference=bool(row[6]),
                certificate_id=row[7],
                ioc_proxy=float(row[8]) if row[8] is not None else None,
                support_count=int(row[9]),
                metadata=_safe_json_load(row[10]),
                created_at=row[11],
            )
            for row in rows
        ]

    def purge_expired_memory_records(self) -> int:
        """B2 - Borra las memorias expiradas (now > created_at + ttl_seconds).

        Devuelve la cantidad de filas borradas. Las memorias con ttl_seconds NULL
        nunca expiran.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM memory_records WHERE {_MEMORY_EXPIRED_SQL}"
            )
            deleted = cursor.rowcount
            conn.commit()
        return int(deleted)

    def write_transfer_assessment(
        self, assessment: TransferAssessmentRecord,
    ) -> TransferAssessmentRecord:
        # B46 - Semantica de created_at: es el TIEMPO DE CREACION del assessment,
        # por lo que se PRESERVA en un re-write del mismo assessment_id (igual que
        # el backend Postgres). Antes se usaba `INSERT OR REPLACE`, que borra la
        # fila e inserta una nueva (pisando created_at con el valor entrante).
        # Ahora usamos upsert (SQLite >= 3.24): actualiza TODAS las columnas
        # EXCEPTO created_at, que conserva el valor original de la fila existente.
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO transfer_assessments
                (assessment_id, run_id, episode_id, source_scenario, target_scenario,
                 compatibility_class, transfer_verdict, memory_purity_score,
                 transition_stability_score, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assessment_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    episode_id=excluded.episode_id,
                    source_scenario=excluded.source_scenario,
                    target_scenario=excluded.target_scenario,
                    compatibility_class=excluded.compatibility_class,
                    transfer_verdict=excluded.transfer_verdict,
                    memory_purity_score=excluded.memory_purity_score,
                    transition_stability_score=excluded.transition_stability_score,
                    metadata=excluded.metadata
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
                    json.dumps(assessment.metadata),
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
            "transition_stability_score, metadata, created_at "
            "FROM transfer_assessments"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            TransferAssessmentRecord(
                assessment_id=row[0],
                run_id=row[1],
                episode_id=row[2],
                source_scenario=row[3],
                target_scenario=row[4],
                compatibility_class=row[5],
                transfer_verdict=row[6],
                memory_purity_score=float(row[7]),
                transition_stability_score=float(row[8]),
                metadata=_safe_json_load(row[9]),
                created_at=row[10],
            )
            for row in rows
        ]

    def write_organism_snapshot(
        self, snapshot: OrganismSnapshotRecord
    ) -> OrganismSnapshotRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO organism_snapshots
                (snapshot_id, run_id, episode_id, trajectory_id, regime, snapshot_json, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    snapshot.episode_id,
                    snapshot.trajectory_id,
                    snapshot.regime,
                    json.dumps(snapshot.snapshot_json),
                    json.dumps(snapshot.metadata),
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
            "SELECT snapshot_id, run_id, episode_id, trajectory_id, regime, snapshot_json, metadata, created_at "
            "FROM organism_snapshots"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = ?")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            OrganismSnapshotRecord(
                snapshot_id=row[0],
                run_id=row[1],
                episode_id=row[2],
                trajectory_id=row[3],
                regime=row[4],
                snapshot_json=_safe_json_load(row[5]),
                metadata=_safe_json_load(row[6]),
                created_at=row[7],
            )
            for row in rows
        ]

    def write_trajectory_window(
        self, window: TrajectoryWindowRecord
    ) -> TrajectoryWindowRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trajectory_windows
                (window_id, run_id, trajectory_id, start_episode, end_episode, snapshots_json, digest_json, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    window.window_id,
                    window.run_id,
                    window.trajectory_id,
                    window.start_episode,
                    window.end_episode,
                    json.dumps(window.snapshots_json),
                    json.dumps(window.digest_json),
                    json.dumps(window.metadata),
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
            "SELECT window_id, run_id, trajectory_id, start_episode, end_episode, snapshots_json, digest_json, metadata, created_at "
            "FROM trajectory_windows"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = ?")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            TrajectoryWindowRecord(
                window_id=row[0],
                run_id=row[1],
                trajectory_id=row[2],
                start_episode=int(row[3]),
                end_episode=int(row[4]),
                snapshots_json=_safe_json_load(row[5]),
                digest_json=_safe_json_load(row[6]),
                metadata=_safe_json_load(row[7]),
                created_at=row[8],
            )
            for row in rows
        ]

    def write_trajectory_flow_report(
        self, report: TrajectoryFlowReportRecord
    ) -> TrajectoryFlowReportRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trajectory_flow_reports
                (report_id, run_id, trajectory_id, window_id, flow_validity, erosion, phase_drift, rollback_obligation, report_json, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.run_id,
                    report.trajectory_id,
                    report.window_id,
                    int(report.flow_validity),
                    report.erosion,
                    report.phase_drift,
                    int(report.rollback_obligation),
                    json.dumps(report.report_json),
                    json.dumps(report.metadata),
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
            "SELECT report_id, run_id, trajectory_id, window_id, flow_validity, erosion, phase_drift, rollback_obligation, report_json, metadata, created_at "
            "FROM trajectory_flow_reports"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = ?")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            TrajectoryFlowReportRecord(
                report_id=row[0],
                run_id=row[1],
                trajectory_id=row[2],
                window_id=row[3],
                flow_validity=bool(row[4]),
                erosion=float(row[5]),
                phase_drift=float(row[6]),
                rollback_obligation=bool(row[7]),
                report_json=_safe_json_load(row[8]),
                metadata=_safe_json_load(row[9]),
                created_at=row[10],
            )
            for row in rows
        ]

    def write_renormalization_event(
        self, event: RenormalizationEventRecord
    ) -> RenormalizationEventRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO renormalization_events
                (event_id, run_id, trajectory_id, source_regime, target_regime, residual_error, transport_uncertainty, expected_recovery_cost, map_json, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(event.map_json),
                    json.dumps(event.metadata),
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
            "SELECT event_id, run_id, trajectory_id, source_regime, target_regime, residual_error, transport_uncertainty, expected_recovery_cost, map_json, metadata, created_at "
            "FROM renormalization_events"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = ?")
            params.append(trajectory_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            RenormalizationEventRecord(
                event_id=row[0],
                run_id=row[1],
                trajectory_id=row[2],
                source_regime=row[3],
                target_regime=row[4],
                residual_error=float(row[5]),
                transport_uncertainty=float(row[6]),
                expected_recovery_cost=float(row[7]),
                map_json=_safe_json_load(row[8]),
                metadata=_safe_json_load(row[9]),
                created_at=row[10],
            )
            for row in rows
        ]

    def write_constitutional_risk_state(
        self, risk_state: ConstitutionalRiskStateRecord
    ) -> ConstitutionalRiskStateRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO constitutional_risk_states
                (state_id, run_id, trajectory_id, scope_type, scope_key, risk_score, risk_json, prev_state_id, step_index, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    risk_state.state_id,
                    risk_state.run_id,
                    risk_state.trajectory_id,
                    risk_state.scope_type,
                    risk_state.scope_key,
                    risk_state.risk_score,
                    json.dumps(risk_state.risk_json),
                    risk_state.prev_state_id,
                    risk_state.step_index,
                    json.dumps(risk_state.metadata),
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
            "SELECT state_id, run_id, trajectory_id, scope_type, scope_key, risk_score, risk_json, prev_state_id, step_index, metadata, created_at "
            "FROM constitutional_risk_states"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = ?")
            params.append(trajectory_id)
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_key:
            clauses.append("scope_key = ?")
            params.append(scope_key)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY step_index DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ConstitutionalRiskStateRecord(
                state_id=row[0],
                run_id=row[1],
                trajectory_id=row[2],
                scope_type=row[3],
                scope_key=row[4],
                risk_score=float(row[5]),
                risk_json=_safe_json_load(row[6]),
                prev_state_id=row[7],
                step_index=int(row[8]),
                metadata=_safe_json_load(row[9]),
                created_at=row[10],
            )
            for row in rows
        ]

    def write_failure_atlas_event(
        self, event: FailureAtlasEventRecord
    ) -> FailureAtlasEventRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO failure_atlas_events
                (event_id, run_id, trajectory_id, scope_type, scope_key, failure_class, severity, reversible, recovery_protocol, signature_json, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.trajectory_id,
                    event.scope_type,
                    event.scope_key,
                    event.failure_class,
                    event.severity,
                    int(event.reversible),
                    event.recovery_protocol,
                    json.dumps(event.signature_json),
                    json.dumps(event.metadata),
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
            "SELECT event_id, run_id, trajectory_id, scope_type, scope_key, failure_class, severity, reversible, recovery_protocol, signature_json, metadata, created_at "
            "FROM failure_atlas_events"
        )
        clauses: list[str] = []
        params: list[object] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trajectory_id:
            clauses.append("trajectory_id = ?")
            params.append(trajectory_id)
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_key:
            clauses.append("scope_key = ?")
            params.append(scope_key)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            FailureAtlasEventRecord(
                event_id=row[0],
                run_id=row[1],
                trajectory_id=row[2],
                scope_type=row[3],
                scope_key=row[4],
                failure_class=row[5],
                severity=row[6],
                reversible=bool(row[7]),
                recovery_protocol=row[8],
                signature_json=_safe_json_load(row[9]),
                metadata=_safe_json_load(row[10]),
                created_at=row[11],
            )
            for row in rows
        ]

    def close(self) -> None:
        # SQLite usa conexiones cortas por operacion; no hay pool que cerrar.
        return None
