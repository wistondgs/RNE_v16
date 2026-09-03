import runpy
from lab.genesis.verifiers import FederationVerdict,adjudicate_requirement,build_requirement_evidence_bundle,validate_requirement_adjudication
h=runpy.run_path("tests/genesis/test_m6b2_evidence.py")
def test_complete_bundle_consumes_all_records_and_preserves_independent_conflict():
 router,plan,subject,records=h["multi_verdict_material"]();bundle=build_requirement_evidence_bundle(router=router,federation_plan=plan,subject=subject,requirement_id="router-requirement",records=records)
 receipt=adjudicate_requirement(router=router,federation_plan=plan,bundle=bundle,subject=subject,records=records)
 assert receipt.verdict is FederationVerdict.CONFLICT
 assert receipt.all_execution_record_hashes==bundle.execution_record_hashes
 assert validate_requirement_adjudication(receipt,router=router,federation_plan=plan,bundle=bundle,subject=subject,records=records)
