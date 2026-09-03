"""M6B-2 structural bundles preserve every planned execution record."""
from __future__ import annotations
import runpy
from lab.genesis.verifiers import (EvidenceBundleStatus, ExecutionRecordMaterial, RequirementEvidenceBundle,
    build_requirement_evidence_bundle, validate_requirement_evidence_bundle)

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
