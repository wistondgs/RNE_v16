"""Bounded exhaustive (n<=2) equivalence: federation remains the oracle."""
from itertools import product
import runpy
from lab.genesis.contracts.receipts import ReceiptStatus,VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers import *
from lab.genesis.verifiers.bindings import canonical_execution_context_hash

base=runpy.run_path("tests/genesis/test_m6a3_router.py"); helpers=base["helpers"]

def materialize(case_id,statuses,q,k,relation):
 desc=tuple(helpers["exact_descriptor"](implementation_identity_hash=helpers["h"]((case_id,n)),verifier_id=f"{case_id}-{n}") for n in range(len(statuses)))
 router,_=base["prepared"](descriptors=desc,req=base["requirement"](count=q,independent=k))
 profile,integrity=router.profiles[0],router.integrities[0];router._profile=lambda _d:profile;router._integrity=lambda _d,_p:integrity
 if relation=="DEPENDENT" and len(desc)==2:router.graph.edges.add(tuple(sorted((desc[0].descriptor_hash,desc[1].descriptor_hash))))
 if relation=="UNKNOWN":router.graph.complete=False
 plan,claim=router.route(),router.claim;cid=helpers["h"]((case_id,"subject"));ctx={"claim":claim,"candidate_identity_hash":cid,"plan_hash":plan.plan_hash,"snapshot_hash":helpers["h"]("snapshot")};ctx["context_hash"]=canonical_execution_context_hash(claim.claim_hash,cid,ctx);subject=ExecutionSubjectBinding(claim.claim_hash,cid,canonical_sha256(claim.domain),ctx["context_hash"])
 class V:
  def __init__(self,d,s):self.verifier_id,self.verifier_version,self.s=d.verifier_id,d.verifier_version,s
  def verify(self,c,_x,x):return VerifierReceipt(f"{self.verifier_id}-r","test",c.claim_hash,x["plan_hash"],x["snapshot_hash"],self.verifier_id,self.verifier_version,self.s,{},(),{},(),{})
 records=[]
 for d,s in zip(desc,statuses):
  b=next(x for x in plan.selected_bindings if x.verifier_id==d.verifier_id);r=plan.routing_results[0];req=PlannedExecutionRequest(plan.plan_hash,r.requirement_id,r.requirement_hash,b.binding_hash,subject.subject_hash);o=PlanBoundExecutionKernel(router).execute(federation_plan=plan,request=req,subject=subject,descriptor=d,verifier=V(d,s),claim=claim,candidate=lambda x:x+1,context=ctx);records.append(ExecutionRecordMaterial(o.record,o.receipt,req,d))
 bundle=build_requirement_evidence_bundle(router=router,federation_plan=plan,subject=subject,requirement_id="router-requirement",records=records)
 return router,plan,subject,tuple(records),bundle

def test_bounded_exhaustive_adjudication_equivalence_n_le_2():
 verdicts=set();count=0
 for n in (1,2):
  for statuses in product(tuple(ReceiptStatus),repeat=n):
   for q in (n,):
    for k in range(1,n+1):
     for relation in (("VERIFIED",) if n==1 or k==2 else ("VERIFIED","DEPENDENT","UNKNOWN")):
      router,plan,subject,records,bundle=materialize(f"{n}-{statuses}-{q}-{k}-{relation}",statuses,q,k,relation)
      expected=adjudicate(router.requirements[0],[(x.descriptor,next(i for i in router.integrities if i.receipt_hash==plan.selected_bindings[[b.binding_hash for b in plan.selected_bindings].index(x.record.selected_verifier_binding_hash)].integrity_receipt_hash),x.record.observed_verdict.value) for x in records],router.graph)
      actual=adjudicate_requirement(router=router,federation_plan=plan,bundle=bundle,subject=subject,records=records)
      assert actual.verdict is expected and actual.all_execution_record_hashes==bundle.execution_record_hashes
      verdicts.add(expected);count+=1
 assert count==68 and {FederationVerdict.PASS,FederationVerdict.FAIL,FederationVerdict.CONFLICT,FederationVerdict.INCONCLUSIVE}<=verdicts
