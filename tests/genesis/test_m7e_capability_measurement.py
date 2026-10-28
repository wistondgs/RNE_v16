"""M7-E exact hidden and transfer measurement before causal attribution."""
from __future__ import annotations
from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.certification import measure_promoted_capability
from lab.genesis.acquisition.contracts import AcquisitionCampaignManifest,CANDIDATE_RANKING_RULE,CapabilityManifest,HUMAN_INTERVENTION_POLICY,PROMOTION_RULE
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.contracts.serialization import canonical_sha256
def h(x):return canonical_sha256({"m7e":x})
def test_promoted_skill_is_exact_on_hidden_ood_and_three_compositional_wrappers()->None:
 s=DSLSpecification("m7","genesis-m7-dsl-v1",(-2,-1,0,1,2,3),5,12,10000);g=CapabilityManifest("g","m7",());c=AcquisitionCampaignManifest("c","m7",h("snap"),g.manifest_hash,s.dsl_hash,h("syn"),{x:h(x) for x in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},h("gen"),{x:h("seed"+x) for x in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},{"max_candidates":256},5,12,s.allowed_constants,tuple(x.value for x in s.operators),CANDIDATE_RANKING_RULE,PROMOTION_RULE,h("cfi"),h("res"),30,HUMAN_INTERVENTION_POLICY,(h("obl"),));b=canonical_benchmark(s,seed=17)
 result=AutonomousAcquisitionCampaign().run(campaign=c,specification=s,benchmark=b,g0_manifest=g,task_id="affine-0",g1_manifest_id="g1");measurement=measure_promoted_capability(result=result,benchmark=b,task_id="affine-0")
 assert measurement.verdict=="PASS" and measurement.hidden.exact_pass and measurement.ood_transfer.exact_pass and len(measurement.compositional)==3 and len({x.result_hash for x in measurement.compositional})==3
