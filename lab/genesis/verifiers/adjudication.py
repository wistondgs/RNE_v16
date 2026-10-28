"""Per-requirement adjudication over a complete, precommitted evidence bundle."""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import combinations
from lab.genesis.contracts.receipts import ReceiptStatus
from lab.genesis.contracts.serialization import canonical_sha256
from .evidence import RequirementEvidenceBundle, ExecutionRecordMaterial, EvidenceBundleStatus, validate_requirement_evidence_bundle
from .execution import ExecutionSubjectBinding
from .federation import FederationVerdict, IntegrityStatus, adjudicate, independent_pass_basis, independent_conflict_basis
from .plan import FederationPlan
from .router import VerifierRouter

@dataclass(frozen=True,slots=True)
class RequirementAdjudicationReceipt:
 schema_version:str;federation_plan_hash:str;requirement_id:str;requirement_hash:str;evidence_bundle_hash:str;execution_subject_hash:str;all_execution_record_hashes:tuple[str,...];verdict:FederationVerdict;qualifying_pass_record_hashes:tuple[str,...];qualifying_fail_record_hashes:tuple[str,...];independent_pass_basis_hashes:tuple[str,...];conflict_basis_hashes:tuple[str,...];unknown_record_hashes:tuple[str,...];error_record_hashes:tuple[str,...];reason_codes:tuple[str,...];receipt_hash:str=field(init=False)
 def __post_init__(self):
  for n in ("all_execution_record_hashes","qualifying_pass_record_hashes","qualifying_fail_record_hashes","independent_pass_basis_hashes","conflict_basis_hashes","unknown_record_hashes","error_record_hashes","reason_codes"):object.__setattr__(self,n,tuple(getattr(self,n)))
  object.__setattr__(self,"verdict",FederationVerdict(self.verdict));object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {k:(getattr(self,k).value if hasattr(getattr(self,k),'value') else getattr(self,k)) for k in ("schema_version","federation_plan_hash","requirement_id","requirement_hash","evidence_bundle_hash","execution_subject_hash","all_execution_record_hashes","verdict","qualifying_pass_record_hashes","qualifying_fail_record_hashes","independent_pass_basis_hashes","conflict_basis_hashes","unknown_record_hashes","error_record_hashes","reason_codes")}
 def validate(self):return self.receipt_hash==canonical_sha256(self.canonical_payload()) and all(getattr(self,n)==tuple(sorted(getattr(self,n))) for n in ("all_execution_record_hashes","qualifying_pass_record_hashes","qualifying_fail_record_hashes","independent_pass_basis_hashes","conflict_basis_hashes","unknown_record_hashes","error_record_hashes","reason_codes"))

def _derive(router,plan,bundle,subject,records):
 records=tuple(records);req=next((x for x in router.requirements if x.requirement_id==bundle.requirement_id),None)
 if req is None or bundle.bundle_status is not EvidenceBundleStatus.COMPLETE or not validate_requirement_evidence_bundle(bundle,router=router,federation_plan=plan,subject=subject,records=records):raise ValueError("genesis_adjudication_bundle_invalid")
 binding={x.binding_hash:x for x in plan.selected_bindings}; eligible=[];unknown=[];errors=[]
 for item in records:
  b=binding[item.record.selected_verifier_binding_hash]; integral=next((x for x in router.integrities if x.receipt_hash==b.integrity_receipt_hash),None)
  if integral and integral.status is IntegrityStatus.PASS and item.descriptor.authority_class in req.accepted_authorities and item.descriptor.verifier_kind in req.accepted_verifier_kinds and (not req.sovereign_required or item.descriptor.sovereignty.value=="SOVEREIGN"):eligible.append(item)
  if item.record.observed_verdict is ReceiptStatus.UNKNOWN:unknown.append(item)
  if item.record.observed_verdict is ReceiptStatus.ERROR:errors.append(item)
 evidence=[(x.descriptor,next((i for i in router.integrities if i.receipt_hash==binding[x.record.selected_verifier_binding_hash].integrity_receipt_hash),None),x.record.observed_verdict.value) for x in records]
 passes=[x for x in eligible if x.record.observed_verdict is ReceiptStatus.PASS];fails=[x for x in eligible if x.record.observed_verdict is ReceiptStatus.FAIL]
 basis_hashes={x[0].descriptor_hash for x in independent_pass_basis(evidence,router.graph,req.min_independent_passes)};basis=tuple(x for x in passes if x.descriptor.descriptor_hash in basis_hashes)
 verdict=adjudicate(req,evidence,router.graph)
 pool_evidence=[x for x in evidence if any(x[0] is item.descriptor for item in eligible)];conflict_descriptors={x[0].descriptor_hash for x in independent_conflict_basis(pool_evidence,router.graph)} if verdict is FederationVerdict.CONFLICT else set();conflict=tuple(x for x in records if x.descriptor.descriptor_hash in conflict_descriptors)
 return req,passes,fails,basis,conflict,unknown,errors,verdict

def adjudicate_requirement(*,router:VerifierRouter,federation_plan:FederationPlan,bundle:RequirementEvidenceBundle,subject:ExecutionSubjectBinding,records:tuple[ExecutionRecordMaterial,...]):
 req,passes,fails,basis,conflict,unknown,errors,verdict=_derive(router,federation_plan,bundle,subject,records)
 hs=lambda xs:tuple(sorted(x.record.record_hash for x in xs));return RequirementAdjudicationReceipt("genesis-requirement-adjudication-v1",federation_plan.plan_hash,req.requirement_id,req.requirement_hash,bundle.bundle_hash,subject.subject_hash,hs(records),verdict,hs(passes),hs(fails),hs(basis),hs(conflict),hs(unknown),hs(errors),())

def validate_requirement_adjudication(receipt,*,router,federation_plan,bundle,subject,records):
 try: expected=adjudicate_requirement(router=router,federation_plan=federation_plan,bundle=bundle,subject=subject,records=tuple(records))
 except ValueError:return False
 return receipt.validate() and receipt.receipt_hash==expected.receipt_hash
