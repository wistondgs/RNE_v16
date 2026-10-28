"""M7-E causal gate: arms are derived; CFI cannot be self-upgraded."""
from __future__ import annotations
from dataclasses import replace
from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.causal import certify_causal_capability
from lab.genesis.acquisition.contracts import *
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.causal.cfi import CFIReport,CFIStatus
from lab.genesis.causal.fork import RootSnapshot
from lab.genesis.contracts.serialization import canonical_sha256
def h(x):return canonical_sha256({"m7e-causal":x})
def material():
 s=DSLSpecification("m7","genesis-m7-dsl-v1",(-2,-1,0,1,2,3),5,12,10000);g=CapabilityManifest("g","m7",());c=AcquisitionCampaignManifest("c","m7",h("snap"),g.manifest_hash,s.dsl_hash,h("syn"),{x:h(x) for x in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},h("gen"),{x:h("s"+x) for x in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},{"max_candidates":256},5,12,s.allowed_constants,tuple(x.value for x in s.operators),CANDIDATE_RANKING_RULE,PROMOTION_RULE,h("cfi"),h("res"),30,HUMAN_INTERVENTION_POLICY,(h("ob"),));b=canonical_benchmark(s,seed=17);r=AutonomousAcquisitionCampaign().run(campaign=c,specification=s,benchmark=b,g0_manifest=g,task_id="affine-0",g1_manifest_id="g1");p=ProgramSkillArtifact("m7","FINITE_INTEGER_FUNCTION",s.dsl_version,{"kind":"integer"},{"kind":"integer"},{"op":"X","args":()},{"node_count":1,"ast_depth":1},("X",),c.campaign_hash,(h("prov"),));root=RootSnapshot("m7",{"g0_manifest_hash":g.manifest_hash,"campaign_hash":c.campaign_hash,"task_id":"affine-0"});return b,r,p,root
def test_causal_certificate_requires_external_cfi_pass_and_all_three_effects():
 b,r,p,root=material();passed=CFIReport("e",("code",),(),(),"ARM_DERIVED",(),CFIStatus.PASS);certificate=certify_causal_capability(root=root,cfi_report=passed,benchmark=b,task_id="affine-0",skill=r.synthesis.selected_skill,placebo=p)
 assert certificate.verdict=="PASS" and certificate.necessity and certificate.sufficiency and certificate.placebo_control
 incomplete=CFIReport("e",("code",),("code",),(),"ARM_DERIVED",(),CFIStatus.INCOMPLETE);assert certify_causal_capability(root=root,cfi_report=incomplete,benchmark=b,task_id="affine-0",skill=r.synthesis.selected_skill,placebo=p).verdict=="NOT_PROVEN"
 try: replace(certificate,verdict="NOT_PROVEN");assert False
 except ValueError: pass
