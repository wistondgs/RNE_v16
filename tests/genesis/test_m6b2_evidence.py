"""M6B-2 structural bundles preserve every planned execution record."""
from __future__ import annotations
import runpy
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers import (EvidenceBundleStatus, ExecutionRecordMaterial, RequirementEvidenceBundle, VerifierExecutionRecord,
    ExecutionSubjectBinding, PlanBoundExecutionKernel, PlannedExecutionRequest, build_requirement_evidence_bundle,
    validate_requirement_evidence_bundle)
from lab.genesis.verifiers.bindings import canonical_execution_context_hash

helpers = runpy.run_path("tests/genesis/test_m6b1_execution.py")

def material():
    outcome, _spy, state = helpers["execute"]()
    router, plan, _claim, descriptor, _context, subject, request = state
    return router, plan, subject, (ExecutionRecordMaterial(outcome.record, outcome.receipt, request, descriptor),)

def test_complete_bundle_derives_plan_bindings_and_is_order_invariant():
    router, plan, subject, records = material()
    bundle = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject,
        requirement_id="router-requirement", records=records)
    again = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject,
        requirement_id="router-requirement", records=tuple(reversed(records)))
    assert bundle.bundle_status is EvidenceBundleStatus.COMPLETE and bundle.bundle_hash == again.bundle_hash
    assert validate_requirement_evidence_bundle(bundle, router=router, federation_plan=plan, subject=subject, records=records)

def test_missing_and_resealed_false_complete_are_not_valid():
    router, plan, subject, _records = material()
    missing = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject,
        requirement_id="router-requirement", records=())
    assert missing.bundle_status is EvidenceBundleStatus.INCOMPLETE_MISSING_RECORDS
    false = RequirementEvidenceBundle(missing.schema_version, missing.federation_plan_hash, missing.requirement_id,
        missing.requirement_hash, missing.execution_subject_hash, missing.expected_selected_binding_hashes,
        missing.execution_record_hashes, EvidenceBundleStatus.COMPLETE, ())
    assert false.validate()
    assert not validate_requirement_evidence_bundle(false, router=router, federation_plan=plan, subject=subject, records=())

def test_cross_subject_and_duplicate_binding_are_structurally_rejected():
    router, plan, subject, records = material(); record = records[0].record
    other_subject = helpers["ExecutionSubjectBinding"](subject.claim_hash, "other", subject.domain_hash, subject.context_hash)
    mixed = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=other_subject,
        requirement_id="router-requirement", records=records)
    assert mixed.bundle_status is EvidenceBundleStatus.INVALID_MIXED_SUBJECT
    duplicate = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject,
        requirement_id="router-requirement", records=records + records)
    assert duplicate.bundle_status is EvidenceBundleStatus.INVALID_DUPLICATE_RECORDS

def test_cross_plan_requirement_and_unplanned_records_are_rejected_before_verdicts():
    router, plan, subject, records = material(); source = records[0]
    def altered(*, plan_hash=None, requirement_hash=None, binding_hash=None):
        r = source.record
        return VerifierExecutionRecord(r.schema_version, plan_hash or r.federation_plan_hash,
            requirement_hash or r.requirement_hash, binding_hash or r.selected_verifier_binding_hash,
            r.execution_subject_hash, r.verifier_id, r.verifier_version, r.descriptor_hash,
            r.implementation_identity_hash, r.qualified_reference_binding_hash, r.verifier_receipt_hash,
            r.observed_verdict, r.semantic_result_hash, r.execution_status, ())
    for record, expected in ((altered(plan_hash="other-plan"), EvidenceBundleStatus.INVALID_MIXED_PLAN),
                             (altered(requirement_hash="other-requirement"), EvidenceBundleStatus.INVALID_MIXED_REQUIREMENT),
                             (altered(binding_hash="unplanned-binding"), EvidenceBundleStatus.INVALID_EXTRA_RECORDS)):
        bundle = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject,
            requirement_id="router-requirement", records=(ExecutionRecordMaterial(record, source.receipt, source.request, source.descriptor),))
        assert bundle.bundle_status is expected

def multi_verdict_material():
    router_test = runpy.run_path("tests/genesis/test_m6a3_router.py")
    h, exact_descriptor, requirement = router_test["helpers"]["h"], router_test["helpers"]["exact_descriptor"], router_test["requirement"]
    descriptors = tuple(exact_descriptor(implementation_identity_hash=h(name), verifier_id=name) for name in ("v1", "v2", "v3", "v4"))
    router, _ = router_test["prepared"](descriptors=descriptors, req=requirement(count=4, independent=1))
    profile, integrity = router.profiles[0], router.integrities[0]
    router._profile = lambda _descriptor: profile
    router._integrity = lambda _descriptor, _profile: integrity
    plan, claim = router.route(), router.claim
    candidate_identity = h("same-subject")
    context = {"claim": claim, "candidate_identity_hash": candidate_identity, "plan_hash": plan.plan_hash, "snapshot_hash": h("snapshot")}
    context["context_hash"] = canonical_execution_context_hash(claim.claim_hash, candidate_identity, context)
    subject = ExecutionSubjectBinding(claim.claim_hash, candidate_identity, canonical_sha256(claim.domain), context["context_hash"])
    class Scripted:
        def __init__(self, descriptor, status): self.verifier_id, self.verifier_version, self.status = descriptor.verifier_id, descriptor.verifier_version, status
        def verify(self, supplied_claim, _candidate, supplied_context):
            return VerifierReceipt(f"receipt-{self.verifier_id}", "test", supplied_claim.claim_hash, supplied_context["plan_hash"], supplied_context["snapshot_hash"], self.verifier_id, self.verifier_version, self.status, {}, (), {}, (), {})
    materials=[]
    for descriptor, status in zip(descriptors, (ReceiptStatus.PASS, ReceiptStatus.FAIL, ReceiptStatus.UNKNOWN, ReceiptStatus.ERROR)):
        binding = next(x for x in plan.selected_bindings if x.verifier_id == descriptor.verifier_id)
        result = plan.routing_results[0]
        request = PlannedExecutionRequest(plan.plan_hash, result.requirement_id, result.requirement_hash, binding.binding_hash, subject.subject_hash)
        outcome = PlanBoundExecutionKernel(router).execute(federation_plan=plan, request=request, subject=subject, descriptor=descriptor, verifier=Scripted(descriptor, status), claim=claim, candidate=lambda x:x+1, context=context)
        assert outcome.record is not None
        materials.append(ExecutionRecordMaterial(outcome.record, outcome.receipt, request, descriptor))
    return router, plan, subject, tuple(materials)

def test_outcome_omission_is_incomplete_while_all_mixed_verdicts_are_complete():
    router, plan, subject, records = multi_verdict_material()
    complete = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject, requirement_id="router-requirement", records=records)
    omitted = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject, requirement_id="router-requirement", records=(records[0], records[2], records[3]))
    assert complete.bundle_status is EvidenceBundleStatus.COMPLETE
    assert {item.record.observed_verdict for item in records} == {ReceiptStatus.PASS, ReceiptStatus.FAIL, ReceiptStatus.UNKNOWN, ReceiptStatus.ERROR}
    assert omitted.bundle_status is EvidenceBundleStatus.INCOMPLETE_MISSING_RECORDS

def test_expected_bindings_and_invalid_execution_record_are_rederived():
    router, plan, subject, records = material()
    bundle = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject, requirement_id="router-requirement", records=records)
    forged = RequirementEvidenceBundle(bundle.schema_version, bundle.federation_plan_hash, bundle.requirement_id, bundle.requirement_hash,
        bundle.execution_subject_hash, ("caller-invented",), bundle.execution_record_hashes, bundle.bundle_status, ())
    assert forged.validate() and not validate_requirement_evidence_bundle(forged, router=router, federation_plan=plan, subject=subject, records=records)
    source = records[0]; invalid = VerifierExecutionRecord(source.record.schema_version, source.record.federation_plan_hash,
        source.record.requirement_hash, source.record.selected_verifier_binding_hash, source.record.execution_subject_hash,
        source.record.verifier_id, source.record.verifier_version, source.record.descriptor_hash, "wrong-implementation",
        source.record.qualified_reference_binding_hash, source.record.verifier_receipt_hash, source.record.observed_verdict,
        source.record.semantic_result_hash, source.record.execution_status, ())
    rejected = build_requirement_evidence_bundle(router=router, federation_plan=plan, subject=subject, requirement_id="router-requirement",
        records=(ExecutionRecordMaterial(invalid, source.receipt, source.request, source.descriptor),))
    assert rejected.bundle_status is EvidenceBundleStatus.ERROR_INVALID_RECORD
