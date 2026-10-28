"""M7-D: immutable G0 baseline, autonomous acquisition, and one-shot promotion."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from lab.genesis.acquisition.benchmark import (
    SealedCapabilityBenchmark,
    SplitEvaluation,
    TaskBenchmarkBinding,
    validate_task_benchmark_binding,
)
from lab.genesis.acquisition.contracts import (AcquisitionCampaignManifest, CandidateCommitment, CapabilityManifest, ProgramSkillArtifact, PromotionReceipt, PromotionStatus, derive_successor_manifest, validate_candidate_commitment, validate_promotion_receipt)
from lab.genesis.acquisition.audit import DurableAuditClaimRegistry, DurableAuditResult
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.synthesis import DeterministicProgramSynthesizer, SynthesisOutcome
from lab.genesis.contracts.serialization import canonical_sha256

@dataclass(frozen=True, slots=True)
class PriorInsufficiencyReceipt:
    schema_version:str; campaign_hash:str; task_id:str; g0_manifest_hash:str; target_skill_hash:str|None; correct:int; total:int; verdict:str; reason_code:str; receipt_hash:str=field(init=False)
    def __post_init__(self)->None:
        if self.verdict not in {"PASS","NOT_PROVEN"} or self.correct<0 or self.total<=0 or self.correct>self.total: raise ValueError("genesis_prior_receipt_invalid")
        object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]:return {"schema_version":self.schema_version,"campaign_hash":self.campaign_hash,"task_id":self.task_id,"g0_manifest_hash":self.g0_manifest_hash,"target_skill_hash":self.target_skill_hash,"correct":self.correct,"total":self.total,"verdict":self.verdict,"reason_code":self.reason_code}
    def validate(self)->bool:return self.receipt_hash==canonical_sha256(self.canonical_payload())

@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    prior:PriorInsufficiencyReceipt; synthesis:SynthesisOutcome; commitment:CandidateCommitment|None; audit:SplitEvaluation|None; promotion:PromotionReceipt; g1_manifest:CapabilityManifest|None; task_benchmark_binding:TaskBenchmarkBinding|None=None; durable_audit:DurableAuditResult|None=None

class AutonomousAcquisitionCampaign:
    """A no-input pipeline: TRAIN -> candidate commitment -> AUDIT once -> G1."""
    def __init__(self,synthesizer:DeterministicProgramSynthesizer|None=None)->None:self._synthesizer=synthesizer or DeterministicProgramSynthesizer()
    def run(self,*,campaign:AcquisitionCampaignManifest,specification:DSLSpecification,benchmark:SealedCapabilityBenchmark,g0_manifest:CapabilityManifest,task_id:str,g1_manifest_id:str,task_benchmark_binding:TaskBenchmarkBinding|None=None,audit_registry:DurableAuditClaimRegistry|None=None)->AcquisitionResult:
        if campaign.g0_capability_manifest_hash!=g0_manifest.manifest_hash or campaign.dsl_hash!=specification.dsl_hash or benchmark.manifest.dsl_hash!=specification.dsl_hash: raise ValueError("genesis_acquisition_binding_invalid")
        if task_benchmark_binding is not None and (
            task_benchmark_binding.task_id != task_id
            or not validate_task_benchmark_binding(
                task_benchmark_binding, campaign=campaign, benchmark=benchmark
            )
        ): raise ValueError("genesis_acquisition_task_benchmark_binding_invalid")
        view=benchmark.learner_view(task_id)
        # G0 has no installed program for this target. The evaluator records the
        # concrete zero-answer behavior rather than inferring absence from a hash.
        prior=PriorInsufficiencyReceipt("genesis-m7-prior-insufficiency-v1",campaign.campaign_hash,task_id,g0_manifest.manifest_hash,None,0,len(view.training_examples),"PASS" if not g0_manifest.skill_hashes else "NOT_PROVEN","no_target_skill_installed" if not g0_manifest.skill_hashes else "baseline_capabilities_present")
        synthesis=self._synthesizer.synthesize(campaign=campaign,specification=specification,training=view)
        if synthesis.selected_skill is None:
            promotion=PromotionReceipt("genesis-m7-promotion-receipt-v1",campaign.campaign_hash,canonical_sha256({"no_candidate":synthesis.receipt.synthesis_hash}),synthesis.receipt.synthesis_hash,canonical_sha256({"no_skill":campaign.campaign_hash}),canonical_sha256({"audit":"not_opened"}),g0_manifest.manifest_hash,None,PromotionStatus.REJECTED,("no_exact_train_candidate",))
            return AcquisitionResult(prior,synthesis,None,None,promotion,None,task_benchmark_binding)
        skill=synthesis.selected_skill
        commitment=CandidateCommitment("genesis-m7-candidate-commitment-v1",skill.skill_hash,campaign.campaign_hash,synthesis.receipt.training_evidence_hash or "",synthesis.receipt.synthesis_hash,synthesis.receipt.ranking_evidence_hash or "")
        if not validate_candidate_commitment(commitment,campaign,synthesis.receipt,skill): raise ValueError("genesis_acquisition_commitment_invalid")
        if campaign.evidence_classification == "CONFIRMATORY_GE_I_EVIDENCE":
            if task_benchmark_binding is None or audit_registry is None:
                raise ValueError("genesis_acquisition_confirmatory_audit_registry_required")
            durable_audit = audit_registry.evaluate(
                campaign=campaign,
                task_binding=task_benchmark_binding,
                commitment=commitment,
                evaluate_once=lambda: benchmark.commit_candidate(task_id, skill).evaluate_once(),
            )
            audit = durable_audit.audit
        else:
            durable_audit = None
            audit=benchmark.commit_candidate(task_id,skill).evaluate_once()
        if audit.exact_pass:
            g1=derive_successor_manifest(g0_manifest,skill,manifest_id=g1_manifest_id,schema_version=g0_manifest.schema_version)
            promotion=PromotionReceipt("genesis-m7-promotion-receipt-v1",campaign.campaign_hash,commitment.commitment_hash,synthesis.receipt.synthesis_hash,skill.skill_hash,audit.result_hash,g0_manifest.manifest_hash,g1.manifest_hash,PromotionStatus.PROMOTED,("audit_exact_pass","candidate_precommitted"))
        else:
            g1=None;promotion=PromotionReceipt("genesis-m7-promotion-receipt-v1",campaign.campaign_hash,commitment.commitment_hash,synthesis.receipt.synthesis_hash,skill.skill_hash,audit.result_hash,g0_manifest.manifest_hash,None,PromotionStatus.REJECTED,("audit_not_exact",))
        if not validate_promotion_receipt(promotion,campaign=campaign,commitment=commitment,synthesis=synthesis.receipt,candidate=skill,g0_manifest=g0_manifest,g1_manifest=g1): raise ValueError("genesis_acquisition_promotion_invalid")
        return AcquisitionResult(prior,synthesis,commitment,audit,promotion,g1,task_benchmark_binding,durable_audit)
