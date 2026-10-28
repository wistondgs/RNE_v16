"""Capa de persistencia hibrida para runtime RNFE."""

from __future__ import annotations

import threading

from .config import StorageConfig
from .contract_validation import ACTIVE_CONTRACTS, ContractViolationError
from .factory import StorageFactory
from .facade import StorageFacade
from .interfaces import (
    ArtifactIndexStore,
    CertificationStore,
    LedgerStore,
    MemoryStore,
    ReasoningTraceStore,
    RealityStore,
    SessionStore,
    T4TrajectoryStore,
    TelemetryStore,
)
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

_storage_lock = threading.Lock()
_storage_singleton: StorageFacade | None = None


def get_storage(
    *,
    config: StorageConfig | None = None,
    refresh: bool = False,
) -> StorageFacade:
    global _storage_singleton
    with _storage_lock:
        if refresh and _storage_singleton is not None:
            _storage_singleton.close()
            _storage_singleton = None
        if _storage_singleton is None:
            effective_config = config or StorageConfig.from_env()
            _storage_singleton = StorageFactory.create_facade(effective_config)
        return _storage_singleton


def reset_storage() -> None:
    global _storage_singleton
    with _storage_lock:
        if _storage_singleton is not None:
            _storage_singleton.close()
            _storage_singleton = None


__all__ = [
    "ACTIVE_CONTRACTS",
    "ArtifactIndexStore",
    "ArtifactRecord",
    "CertificationStore",
    "ConstitutionalRiskStateRecord",
    "ContractViolationError",
    "EpisodeCertificateRecord",
    "FailureAtlasEventRecord",
    "LedgerStore",
    "MemoryRecord",
    "MemoryStore",
    "OrganismSnapshotRecord",
    "PromotionDecisionRecord",
    "RenormalizationEventRecord",
    "ReasoningTraceRecord",
    "RealityAssessmentRecord",
    "RealityBenchRunRecord",
    "ReasoningTraceStore",
    "RealityStore",
    "SessionBridgeRecord",
    "SessionStore",
    "T4TrajectoryStore",
    "StorageConfig",
    "StorageFactory",
    "StorageFacade",
    "StoredEvent",
    "TelemetrySnapshotRecord",
    "TelemetryStore",
    "TrajectoryFlowReportRecord",
    "TrajectoryWindowRecord",
    "TransferAssessmentRecord",
    "get_storage",
    "reset_storage",
]
