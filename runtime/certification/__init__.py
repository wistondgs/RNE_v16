"""Certificación episódica y gates de promoción para RNFE."""

from .certificate_builder import CertificateBuilder
from .coherence_obstruction import (
    CoherenceObstructionTracker,
    cycle_error,
    section_divergence,
    section_from_certificate,
    section_from_episode_result,
)
from .continuity_guard import ContinuityGuard
from .ioc_proxy import IoCProxy
from .promotion_gate import PromotionGate
from .risk_engine import (
    EpisodeRiskTracker,
    agresti_coull_lcb,
    compute_b_safe,
    compute_cvar,
    sie_rule,
)
from .trace_integrity import TraceIntegrityResult, assess_trace_integrity

__all__ = [
    "CertificateBuilder",
    "CoherenceObstructionTracker",
    "ContinuityGuard",
    "EpisodeRiskTracker",
    "cycle_error",
    "section_divergence",
    "section_from_certificate",
    "section_from_episode_result",
    "IoCProxy",
    "PromotionGate",
    "agresti_coull_lcb",
    "compute_b_safe",
    "compute_cvar",
    "sie_rule",
    "TraceIntegrityResult",
    "TransferAssessment",
    "TransferVerdict",
    "assess_trace_integrity",
    "assess_transfer",
]


def __getattr__(name: str):
    if name in ("TransferAssessment", "TransferVerdict", "assess_transfer"):
        from .transfer_assessment import TransferAssessment, TransferVerdict, assess_transfer
        _map = {
            "TransferAssessment": TransferAssessment,
            "TransferVerdict": TransferVerdict,
            "assess_transfer": assess_transfer,
        }
        return _map[name]
    raise AttributeError(name)
