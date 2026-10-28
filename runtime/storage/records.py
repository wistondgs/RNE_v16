"""Tipos de datos persistentes para la capa de storage RNFE."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    """Devuelve timestamp ISO-8601 en UTC."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class StoredEvent:
    event_type: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)
    run_id: Optional[str] = None
    source: Optional[str] = None
    legacy_db_path: Optional[str] = None
    legacy_event_id: Optional[int] = None
    event_id: Optional[str] = None
    payload_hash: Optional[str] = None


@dataclass(slots=True)
class TelemetrySnapshotRecord:
    snapshot_id: str
    metrics: Dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)
    run_id: Optional[str] = None


@dataclass(slots=True)
class ReasoningTraceRecord:
    trace_id: str
    step_index: int
    family: str
    status: str
    detail: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)
    run_id: Optional[str] = None


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    rel_path: str
    abs_path: str
    sha256: str
    size_bytes: int
    created_at: str = field(default_factory=utc_now_iso)
    run_id: Optional[str] = None
    mime_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionBridgeRecord:
    session_id: str
    episode_id: str
    channel: str
    timestamp: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RealityAssessmentRecord:
    assessment_id: str
    episode_id: str
    closure_passed: bool
    continuity_score: float
    trace_integrity: bool
    collapse_detected: bool
    created_at: str = field(default_factory=utc_now_iso)
    run_id: Optional[str] = None
    bench_run_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RealityBenchRunRecord:
    bench_run_id: str
    total_episodes: int
    closure_rate: float
    continuity_mean: float
    collapse_count: int
    gate_profile: str
    passed: bool
    created_at: str = field(default_factory=utc_now_iso)
    run_id: Optional[str] = None
    summary: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EpisodeCertificateRecord:
    certificate_id: str
    episode_id: str
    run_id: str
    trace_id: str
    smg_artifacts: Dict[str, Any]
    lotf_artifacts: Dict[str, Any]
    world_artifacts: Dict[str, Any]
    continuity_score: float
    ioc_proxy: float
    risk_score: float
    verdict: str
    rollback_ready: bool
    promotion_candidate: bool
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PromotionDecisionRecord:
    decision_id: str
    episode_id: str
    run_id: str
    certificate_id: str
    verdict: str
    reason: str
    rollback_ready: bool
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRecord:
    """Registro de memoria multiescala.

    B24 — ADVERTENCIA sobre `no_interference`: **NO CONFIAR EN ESTE VALOR.**
    """

    memory_id: str
    run_id: str
    episode_id: str
    scale: str
    structure_json: Dict[str, Any]
    ttl_seconds: Optional[int] = None

    # ─────────────────────────────────────────────────────────────────────────
    # B24: CAMPO NO COMPUTADO. NO CONFIAR EN ESTE VALOR.
    #
    # `no_interference` NO se mide ni se calcula en ningún lado: se escribe
    # `True` por default de schema en TODOS los sitios de escritura
    # (`runtime/memory/mfm_lite/episode_store.py:35,61,88`,
    #  `runtime/organism/experience.py:221`, `runtime/storage/facade.py`).
    # La columna es NOT NULL (`sqlite_store.py:186`, `postgres/schema.sql:127`).
    #
    # No hay NINGÚN consumidor en `runtime/`: nadie lo lee para decidir nada
    # (los backends solo lo persisten y lo devuelven en el round-trip).
    # Es decir: es una AFIRMACIÓN FALSA guardada en el ledger — el organismo
    # declara "esta memoria no interfiere con otras" sin haberlo verificado.
    #
    # El canon lo lista como desiderátum de la memoria ("no interferencia",
    # `canon/experimental/RNFE_blueprint_matematico_latex.md:649`;
    # "no-interferencia", `canon/provisional/ROADMAP_RNFE_v2.md:201`) pero NO lo
    # define operativamente en ningún lado, y nada en `canon/normative/` fija un
    # criterio computable. Por eso NO se inventa una lógica que lo haga "parecer"
    # computado: queda declarado como no computado.
    #
    # Pendiente de decisión (ver informe P9): o se define el criterio y se
    # computa, o se retira la columna. Migrar a nullable es caro (NOT NULL).
    # Hasta entonces: ningún consumidor debe tratar este campo como evidencia
    # de que la memoria no interfiere.
    # ─────────────────────────────────────────────────────────────────────────
    no_interference: bool = True

    certificate_id: Optional[str] = None
    ioc_proxy: Optional[float] = None
    support_count: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TransferAssessmentRecord:
    """Record persistente para evaluación de transferibilidad entre escenarios."""

    assessment_id: str
    run_id: str
    episode_id: str
    source_scenario: str
    target_scenario: str
    compatibility_class: str
    transfer_verdict: str
    memory_purity_score: float
    transition_stability_score: float
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrganismSnapshotRecord:
    snapshot_id: str
    run_id: str
    episode_id: str
    trajectory_id: str
    regime: str
    snapshot_json: Dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrajectoryWindowRecord:
    window_id: str
    run_id: str
    trajectory_id: str
    start_episode: int
    end_episode: int
    snapshots_json: Dict[str, Any]
    digest_json: Dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrajectoryFlowReportRecord:
    report_id: str
    run_id: str
    trajectory_id: str
    window_id: str
    flow_validity: bool
    erosion: float
    phase_drift: float
    rollback_obligation: bool
    report_json: Dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RenormalizationEventRecord:
    event_id: str
    run_id: str
    trajectory_id: str
    source_regime: str
    target_regime: str
    residual_error: float
    transport_uncertainty: float
    expected_recovery_cost: float
    map_json: Dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConstitutionalRiskStateRecord:
    state_id: str
    run_id: str
    trajectory_id: str
    scope_type: str
    scope_key: str
    risk_score: float
    risk_json: Dict[str, Any]
    prev_state_id: Optional[str] = None
    step_index: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FailureAtlasEventRecord:
    event_id: str
    run_id: str
    trajectory_id: str
    scope_type: str
    scope_key: str
    failure_class: str
    severity: str
    reversible: bool
    recovery_protocol: str
    signature_json: Dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)
