"""Immutable contracts for M7 autonomous capability acquisition."""

from .contracts import (
    AcquisitionCampaignManifest,
    CandidateCommitment,
    CapabilityManifest,
    ProgramSkillArtifact,
    PromotionReceipt,
    PromotionStatus,
    SynthesisReceipt,
    SynthesisTermination,
    derive_successor_manifest,
    validate_campaign_binding,
    validate_candidate_commitment,
    validate_manifest_successor,
    validate_promotion_receipt,
    validate_synthesis_receipt,
)

__all__ = [
    "AcquisitionCampaignManifest",
    "CandidateCommitment",
    "CapabilityManifest",
    "ProgramSkillArtifact",
    "PromotionReceipt",
    "PromotionStatus",
    "SynthesisReceipt",
    "SynthesisTermination",
    "derive_successor_manifest",
    "validate_campaign_binding",
    "validate_candidate_commitment",
    "validate_manifest_successor",
    "validate_promotion_receipt",
    "validate_synthesis_receipt",
]
