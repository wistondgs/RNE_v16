"""M7-D prior-insufficiency, commitment, audit and promotion gates."""
from __future__ import annotations
from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.contracts import AcquisitionCampaignManifest,CANDIDATE_RANKING_RULE,CapabilityManifest,HUMAN_INTERVENTION_POLICY,PROMOTION_RULE,PromotionStatus,validate_manifest_successor
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.contracts.serialization import canonical_sha256
def h(x:str)->str:return canonical_sha256({"m7d":x})
def make(budget:int=256):
 s=DSLSpecification("m7","genesis-m7-dsl-v1",(-2,-1,0,1,2,3),5,12,10000);g0=CapabilityManifest("g0","m7",())
 c=AcquisitionCampaignManifest("c","m7",h("snapshot"),g0.manifest_hash,s.dsl_hash,h("synth"),{x:h(x) for x in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},h("generator"),{x:h("seed"+x) for x in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},{"max_candidates":budget},5,12,s.allowed_constants,tuple(x.value for x in s.operators),CANDIDATE_RANKING_RULE,PROMOTION_RULE,h("cfi"),h("resources"),30,HUMAN_INTERVENTION_POLICY,(h("obligation"),))
 return s,g0,c,canonical_benchmark(s,seed=17)
def test_autonomous_campaign_proves_prior_absence_then_promotes_exact_audited_skill()->None:
 s,g0,c,b=make();result=AutonomousAcquisitionCampaign().run(campaign=c,specification=s,benchmark=b,g0_manifest=g0,task_id="affine-0",g1_manifest_id="g1")
 assert result.prior.verdict=="PASS" and result.prior.correct==0 and result.commitment is not None
 assert result.audit.exact_pass and result.promotion.status is PromotionStatus.PROMOTED
 assert g0.skill_hashes==() and validate_manifest_successor(result.g1_manifest,g0,result.synthesis.selected_skill)
def test_budget_failure_never_creates_commitment_audit_or_g1()->None:
 s,g0,c,b=make(1);result=AutonomousAcquisitionCampaign().run(campaign=c,specification=s,benchmark=b,g0_manifest=g0,task_id="affine-0",g1_manifest_id="g1")
 assert result.commitment is None and result.audit is None and result.g1_manifest is None and result.promotion.status is PromotionStatus.REJECTED
