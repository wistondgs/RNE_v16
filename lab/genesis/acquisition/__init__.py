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
from .dsl import (
    DSLEvaluationError,
    DSLSpecification,
    DSLValidationError,
    ProgramOperator,
    canonical_expression,
    evaluate_expression,
    expression_metrics,
    validate_program_skill,
)
from .benchmark import (
    AuditAccess, BenchmarkManifest, BenchmarkTaskDescriptor, DatasetSplit, Example,
    LearnerTrainingView, SealedCapabilityBenchmark, SplitEvaluation, TaskFamily,
    TaskBenchmarkBinding, canonical_benchmark, validate_task_benchmark_binding,
)
from .synthesis import DeterministicProgramSynthesizer, SynthesisOutcome
from .campaign import AcquisitionResult, AutonomousAcquisitionCampaign, PriorInsufficiencyReceipt
from .certification import CapabilityMeasurementReceipt, measure_promoted_capability
from .confirmation import (
    CANONICAL_CONFIRMATORY_TASK_IDS,
    CampaignGate,
    GEIAcceptancePolicy,
    confirmatory_policy,
)
from .audit import (
    AuditClaimReceipt,
    AuditEvaluationReceipt,
    AuditSlot,
    DurableAuditClaimRegistry,
)
from .causal import CapabilityCausalArm, CapabilityCausalCertificate, certify_causal_capability
from .m5_capability_runtime import (
    CapabilityArmRuntime,
    CapabilityExecutionBinding,
    CapabilityMeasurementOracle,
    CapabilityOperation,
    CapabilityStateAction,
    capability_root_state,
)
from .causal_experiments import (
    CausalArmClosure,
    CausalAttributionStatus,
    CausalCapabilityAttribution,
    CausalExperiment,
    FreshBaselineReceipt,
    PlaceboCommitment,
    materialize_causal_capability_attribution,
)
from .causal_replay import (
    CausalEvidenceManifest,
    CausalReplayPlan,
    M7CausalReplay,
    PersistedCausalEvidence,
    persist_causal_capability_attribution,
    replay_causal_capability_attribution,
)
from .federated_evidence import (
    FederatedMeasurementScope,
    M7FederatedEvidence,
    ReferenceTargetCommitment,
    materialize_promoted_skill_evidence,
)
from .composition import (
    CompositionalTransferBinding,
    CompositionalTransferEvidence,
    CompositionalTransferProtocol,
    CompositionalWrapper,
    M7CompositionalReplay,
    compositional_transfer_protocol_commitment,
    confirmatory_compositional_transfer_protocol,
    materialize_compositional_transfer_evidence,
    replay_compositional_transfer_evidence,
    wrapper_implementation_hash,
)
from .replay import (
    M7FederatedReplay,
    replay_m7_capability_arm_evidence,
    replay_m7_federated_evidence,
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
    "DSLEvaluationError",
    "DSLSpecification",
    "DSLValidationError",
    "ProgramOperator",
    "canonical_expression",
    "evaluate_expression",
    "expression_metrics",
    "validate_program_skill",
    "AuditAccess", "BenchmarkManifest", "BenchmarkTaskDescriptor", "DatasetSplit", "Example",
    "LearnerTrainingView", "SealedCapabilityBenchmark", "SplitEvaluation", "TaskFamily",
    "TaskBenchmarkBinding", "canonical_benchmark", "validate_task_benchmark_binding",
    "DeterministicProgramSynthesizer", "SynthesisOutcome",
    "AcquisitionResult", "AutonomousAcquisitionCampaign", "PriorInsufficiencyReceipt",
    "CapabilityMeasurementReceipt", "measure_promoted_capability",
    "CANONICAL_CONFIRMATORY_TASK_IDS", "CampaignGate", "GEIAcceptancePolicy",
    "confirmatory_policy",
    "AuditClaimReceipt", "AuditEvaluationReceipt", "AuditSlot", "DurableAuditClaimRegistry",
    "CapabilityCausalArm", "CapabilityCausalCertificate", "certify_causal_capability",
    "CapabilityArmRuntime", "CapabilityExecutionBinding", "CapabilityMeasurementOracle",
    "CapabilityOperation", "CapabilityStateAction", "capability_root_state",
    "CausalArmClosure", "CausalAttributionStatus", "CausalCapabilityAttribution",
    "CausalExperiment", "FreshBaselineReceipt", "PlaceboCommitment",
    "materialize_causal_capability_attribution",
    "CausalEvidenceManifest", "CausalReplayPlan", "M7CausalReplay",
    "PersistedCausalEvidence", "persist_causal_capability_attribution",
    "replay_causal_capability_attribution",
    "FederatedMeasurementScope", "M7FederatedEvidence", "ReferenceTargetCommitment",
    "materialize_promoted_skill_evidence",
    "CompositionalTransferBinding", "CompositionalTransferEvidence",
    "CompositionalTransferProtocol", "CompositionalWrapper", "M7CompositionalReplay",
    "compositional_transfer_protocol_commitment",
    "confirmatory_compositional_transfer_protocol",
    "materialize_compositional_transfer_evidence",
    "replay_compositional_transfer_evidence", "wrapper_implementation_hash",
    "M7FederatedReplay", "replay_m7_capability_arm_evidence", "replay_m7_federated_evidence",
]
