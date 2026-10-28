"""T2: hash-valid but semantically false adjudication receipts are rejected."""
import runpy
from lab.genesis.verifiers import FederationVerdict,RequirementAdjudicationReceipt,adjudicate_requirement,build_requirement_evidence_bundle,validate_requirement_adjudication
h=runpy.run_path("tests/genesis/test_m6b2_evidence.py")
def fixture():
 router,plan,subject,records=h["multi_verdict_material"]();bundle=build_requirement_evidence_bundle(router=router,federation_plan=plan,subject=subject,requirement_id="router-requirement",records=records);receipt=adjudicate_requirement(router=router,federation_plan=plan,bundle=bundle,subject=subject,records=records);return router,plan,subject,records,bundle,receipt
def reseal(receipt,**change):
 p=receipt.canonical_payload()|change
 return RequirementAdjudicationReceipt(p["schema_version"],p["federation_plan_hash"],p["requirement_id"],p["requirement_hash"],p["evidence_bundle_hash"],p["execution_subject_hash"],p["all_execution_record_hashes"],p["verdict"],p["qualifying_pass_record_hashes"],p["qualifying_fail_record_hashes"],p["independent_pass_basis_hashes"],p["conflict_basis_hashes"],p["unknown_record_hashes"],p["error_record_hashes"],p["reason_codes"])
def valid(args,r):return validate_requirement_adjudication(r,router=args[0],federation_plan=args[1],subject=args[2],records=args[3],bundle=args[4])
def test_resealed_false_verdicts_and_bases_are_semantically_rejected():
 args=fixture();receipt=args[-1];assert receipt.validate() and valid(args,receipt)
 for verdict in (FederationVerdict.PASS,FederationVerdict.FAIL,FederationVerdict.INCONCLUSIVE):
  false=reseal(receipt,verdict=verdict.value);assert false.validate() and not valid(args,false)
 for field,value in (("all_execution_record_hashes",receipt.all_execution_record_hashes[:-1]),("conflict_basis_hashes",()),("qualifying_fail_record_hashes",()),("independent_pass_basis_hashes",("invented",))):
  false=reseal(receipt,**{field:value});assert false.validate() and not valid(args,false)
