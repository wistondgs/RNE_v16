"""Bounded exhaustive (n<=2) equivalence: federation remains the oracle.

The exported case domain and materializer are deliberately reused by T2.  That
keeps adversarial receipt tests in the exact planner-reachable state space that
this test certifies, rather than creating a second fixture language.
"""
from dataclasses import dataclass
from itertools import product
import runpy
from lab.genesis.contracts.receipts import ReceiptStatus,VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers import (
    ExecutionRecordMaterial, ExecutionSubjectBinding, FederationVerdict,
    PlanBoundExecutionKernel, PlannedExecutionRequest, adjudicate,
    adjudicate_requirement, build_requirement_evidence_bundle,
    independent_conflict_basis, independent_pass_basis,
)
from lab.genesis.verifiers.bindings import canonical_execution_context_hash

base=runpy.run_path("tests/genesis/test_m6a3_router.py"); helpers=base["helpers"]


@dataclass(frozen=True, slots=True)
class AdjudicationCaseSpec:
 n: int
 statuses: tuple[ReceiptStatus, ...]
 q: int
 k: int
 relation: str
 @property
 def case_spec_hash(self):
  return canonical_sha256({"n":self.n,"statuses":tuple(x.value for x in self.statuses),"q":self.q,"k":self.k,"relation":self.relation})


def planner_reachable_case_specs():
 """The finite, planner-reachable T1 domain (68 states)."""
 for n in (1,2):
  for statuses in product(tuple(ReceiptStatus),repeat=n):
   for q in (n,):
    for k in range(1,n+1):
     for relation in (("VERIFIED",) if n==1 or k==2 else ("VERIFIED","DEPENDENT","UNKNOWN")):
      yield AdjudicationCaseSpec(n,statuses,q,k,relation)


def reachable_domain_hash(specs=None):
 specs=tuple(planner_reachable_case_specs() if specs is None else specs)
 return canonical_sha256(tuple(sorted(x.case_spec_hash for x in specs)))

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


def materialize_spec(spec):
 return materialize(spec.case_spec_hash,spec.statuses,spec.q,spec.k,spec.relation)


def federation_evidence(router, plan, records):
 bindings={x.binding_hash:x for x in plan.selected_bindings}
 integrities={x.receipt_hash:x for x in router.integrities}
 return tuple((x.descriptor,integrities[bindings[x.record.selected_verifier_binding_hash].integrity_receipt_hash],x.record.observed_verdict.value) for x in records)


def federation_verdict(router, plan, records):
 return adjudicate(router.requirements[0],federation_evidence(router,plan,records),router.graph)


def federation_derivation(router, plan, records):
 evidence=federation_evidence(router,plan,records); req=router.requirements[0]
 hashes=lambda items:tuple(sorted(x.record.record_hash for x in items))
 by_descriptor={x.descriptor.descriptor_hash:x for x in records}
 pass_basis=independent_pass_basis(evidence,router.graph,req.min_independent_passes)
 conflict_basis=independent_conflict_basis(evidence,router.graph) if federation_verdict(router,plan,records) is FederationVerdict.CONFLICT else ()
 return {
  "qualifying_pass_record_hashes":hashes(x for x in records if x.record.observed_verdict is ReceiptStatus.PASS),
  "qualifying_fail_record_hashes":hashes(x for x in records if x.record.observed_verdict is ReceiptStatus.FAIL),
  "independent_pass_basis_hashes":hashes(by_descriptor[x[0].descriptor_hash] for x in pass_basis),
  "conflict_basis_hashes":hashes(by_descriptor[x[0].descriptor_hash] for x in conflict_basis),
  "unknown_record_hashes":hashes(x for x in records if x.record.observed_verdict is ReceiptStatus.UNKNOWN),
  "error_record_hashes":hashes(x for x in records if x.record.observed_verdict is ReceiptStatus.ERROR),
 }

def test_bounded_exhaustive_adjudication_equivalence_n_le_2():
 verdicts=set();count=0
 specs=tuple(planner_reachable_case_specs())
 for spec in specs:
  router,plan,subject,records,bundle=materialize_spec(spec)
  expected=federation_verdict(router,plan,records)
  actual=adjudicate_requirement(router=router,federation_plan=plan,bundle=bundle,subject=subject,records=records)
  assert actual.verdict is expected and actual.all_execution_record_hashes==bundle.execution_record_hashes
  for field,value in federation_derivation(router,plan,records).items():assert getattr(actual,field)==value
  verdicts.add(expected);count+=1
 assert count==68 and {FederationVerdict.PASS,FederationVerdict.FAIL,FederationVerdict.CONFLICT,FederationVerdict.INCONCLUSIVE}<=verdicts
 assert reachable_domain_hash(specs)=="f00ddf3bf213d2d9b189f3392700deb7f477fe14befddd2833d6d49d400ac905"
