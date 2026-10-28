"""M6B-1 plan-bound execution tests: admission precedes every verifier call."""
from __future__ import annotations

import runpy

from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.contracts.verification import VerificationObligation, VerificationPlan
from lab.genesis.verifiers import (
    AuthorityClass, DifferentialVerifier, ExecutionAdmissionStatus, ExecutionStatus, ExecutionSubjectBinding,
    FederatedVerificationRequirement, FederationPlan, IntegrityStatus, PlanBoundExecutionKernel,
    PlannedExecutionRequest, QualifiedReferenceBinding, ReferenceDescriptor, ReferenceQualificationPolicy,
    ReferenceRegistry, VerifierDependencyGraph, VerifierIntegrityReceipt, VerifierKind, VerifierRegistry,
    VerifierReliabilityCampaign, VerifierRouter, VerifierExecutionRecord, qualify_reference,
    semantic_result_hash, validate_execution_record,
)
from lab.genesis.verifiers.bindings import canonical_execution_context_hash

router_helpers = runpy.run_path("tests/genesis/test_m6a3_router.py")
case_helpers = router_helpers["helpers"]


class SpyExact:
    verifier_id = "genesis.exact_function"
    verifier_version = "v1"

    def __init__(self):
        self.calls = 0
        self.inner = case_helpers["ExactVerifier"]()

    def verify(self, claim, candidate, context):
        self.calls += 1
        return self.inner.verify(claim, candidate, context)


class UnknownVerifier:
    verifier_id = "genesis.exact_function"
    verifier_version = "v1"
    def __init__(self): self.calls = 0
    def verify(self, claim, _candidate, context):
        self.calls += 1
        return VerifierReceipt("unknown", "test", claim.claim_hash, context["plan_hash"], context["snapshot_hash"],
                               self.verifier_id, self.verifier_version, ReceiptStatus.UNKNOWN, {}, (), {}, (), {})


def prepared():
    router, (descriptor,) = router_helpers["prepared"]()
    plan, claim = router.route(), router.claim
    candidate_identity_hash = case_helpers["h"]("m6b1-candidate")
    context = {"claim": claim, "candidate_identity_hash": candidate_identity_hash,
               "plan_hash": plan.plan_hash, "snapshot_hash": case_helpers["h"]("m6b1-snapshot")}
    context["context_hash"] = canonical_execution_context_hash(claim.claim_hash, candidate_identity_hash, context)
    subject = ExecutionSubjectBinding(claim.claim_hash, candidate_identity_hash, canonical_sha256(claim.domain), context["context_hash"])
    result = plan.routing_results[0]
    request = PlannedExecutionRequest(plan.plan_hash, result.requirement_id, result.requirement_hash,
                                      plan.selected_bindings[0].binding_hash, subject.subject_hash)
    return router, plan, claim, descriptor, context, subject, request


def execute(**changes):
    router, plan, claim, descriptor, context, subject, request = prepared()
    spy = changes.pop("verifier", SpyExact())
    result = PlanBoundExecutionKernel(router).execute(federation_plan=changes.pop("plan", plan),
        request=changes.pop("request", request), subject=changes.pop("subject", subject),
        descriptor=changes.pop("descriptor", descriptor), verifier=spy, claim=claim,
        candidate=changes.pop("candidate", case_helpers["plus_one"]), context=changes.pop("context", context), **changes)
    return result, spy, (router, plan, claim, descriptor, context, subject, request)


def generic_router(claim, descriptor, campaign, profile, obligation_id, authority, kind):
    registry = VerifierRegistry(); registry.register(descriptor)
    graph = VerifierDependencyGraph(); graph.add(descriptor)
    requirement = FederatedVerificationRequirement(obligation_id, obligation_id, (authority,), (kind,), 1, 1, False)
    plan = VerificationPlan(f"m6b1-{obligation_id}", claim.claim_hash,
        (VerificationObligation(obligation_id, obligation_id, "candidate", authority.value, (descriptor.verifier_id,), "fail"),), {}, {})
    integrity = VerifierIntegrityReceipt(f"m6b1-{obligation_id}-integrity", descriptor.descriptor_hash,
        descriptor.implementation_identity_hash, descriptor.implementation_identity_hash, descriptor.dependency_manifest_hash,
        profile.profile_hash, IntegrityStatus.PASS, ())
    return VerifierRouter(claim=claim, verification_plan=plan, requirements=(requirement,), registry=registry,
        dependency_graph=graph, reliability_profiles=(profile,), campaign_receipts=(campaign,), integrity_receipts=(integrity,))


def planned_context(router, plan, claim, candidate_identity, extra):
    context = {"claim": claim, "candidate_identity_hash": candidate_identity, "plan_hash": plan.plan_hash,
               "snapshot_hash": canonical_sha256({"m6b1": "snapshot"}), **extra}
    context["context_hash"] = canonical_execution_context_hash(claim.claim_hash, candidate_identity, context)
    subject = ExecutionSubjectBinding(claim.claim_hash, candidate_identity, canonical_sha256(claim.domain), context["context_hash"])
    result, binding = plan.routing_results[0], plan.selected_bindings[0]
    return context, subject, PlannedExecutionRequest(plan.plan_hash, result.requirement_id, result.requirement_hash, binding.binding_hash, subject.subject_hash)


def test_valid_plan_executes_exactly_once_and_preserves_pass():
    outcome, spy, state = execute()
    assert outcome.admission.status is ExecutionAdmissionStatus.ADMITTED
    assert spy.calls == 1 and outcome.receipt.status is ReceiptStatus.PASS
    assert outcome.record.execution_status is ExecutionStatus.EXECUTED
    router, plan, _claim, descriptor, _context, subject, request = state
    assert validate_execution_record(outcome.record, receipt=outcome.receipt, subject=subject, request=request,
                                    binding=plan.selected_bindings[0], descriptor=descriptor)


def test_subject_binding_is_deterministic_and_candidate_sensitive():
    _, _, _, _, context, subject, _ = prepared()
    same = ExecutionSubjectBinding(subject.claim_hash, subject.candidate_identity_hash, subject.domain_hash, subject.context_hash)
    changed = ExecutionSubjectBinding(subject.claim_hash, case_helpers["h"]("other-candidate"), subject.domain_hash, subject.context_hash)
    assert same.subject_hash == subject.subject_hash and changed.subject_hash != subject.subject_hash
    assert context["context_hash"] == subject.context_hash


def test_rejections_call_no_verifier_for_plan_binding_and_subject_tampering():
    _router, plan, _claim, descriptor, _context, subject, request = prepared()
    false_plan = FederationPlan(plan.schema_version, plan.claim_hash, plan.verification_plan_hash,
        plan.requirement_hashes, plan.routing_results, (), plan.dependency_graph_hash, (), (), (),
        plan.cfi_report_hashes, plan.selection_policy_hash)
    outcome, spy, _ = execute(plan=false_plan)
    assert outcome.admission.status is ExecutionAdmissionStatus.REJECTED_PLAN_INVALID and spy.calls == 0
    wrong_descriptor = case_helpers["exact_descriptor"](implementation_identity_hash=case_helpers["h"]("other"))
    outcome, spy, _ = execute(descriptor=wrong_descriptor)
    assert outcome.admission.status is ExecutionAdmissionStatus.REJECTED_BINDING_MISMATCH and spy.calls == 0
    wrong_subject = ExecutionSubjectBinding(subject.claim_hash, subject.candidate_identity_hash, subject.domain_hash, case_helpers["h"]("wrong-context"))
    bad_request = PlannedExecutionRequest(request.federation_plan_hash, request.requirement_id, request.requirement_hash,
                                          request.selected_verifier_binding_hash, wrong_subject.subject_hash)
    outcome, spy, _ = execute(subject=wrong_subject, request=bad_request)
    assert outcome.admission.status is ExecutionAdmissionStatus.REJECTED_SUBJECT_INVALID and spy.calls == 0


def test_fail_and_error_are_executed_verdicts_not_admission_rejections():
    outcome, spy, _ = execute(candidate=case_helpers["x_plus_two"])
    assert spy.calls == 1 and outcome.admission.status is ExecutionAdmissionStatus.ADMITTED
    assert outcome.receipt.status is ReceiptStatus.FAIL
    outcome, spy, _ = execute(candidate=None)
    assert spy.calls == 1 and outcome.admission.status is ExecutionAdmissionStatus.ADMITTED
    assert outcome.receipt.status is ReceiptStatus.ERROR


def test_unknown_is_an_executed_verdict_and_never_triggers_rerouting():
    unknown = UnknownVerifier()
    outcome, spy, _ = execute(verifier=unknown)
    assert spy is unknown and unknown.calls == 1
    assert outcome.admission.status is ExecutionAdmissionStatus.ADMITTED
    assert outcome.receipt.status is ReceiptStatus.UNKNOWN and outcome.record.observed_verdict is ReceiptStatus.UNKNOWN


def test_resealed_record_with_receipt_identity_mismatch_is_rejected():
    outcome, _spy, state = execute()
    _router, plan, _claim, descriptor, _context, subject, request = state
    record = outcome.record
    false = VerifierExecutionRecord(record.schema_version, record.federation_plan_hash, record.requirement_hash,
        record.selected_verifier_binding_hash, record.execution_subject_hash, record.verifier_id, record.verifier_version,
        record.descriptor_hash, case_helpers["h"]("false-implementation"), record.qualified_reference_binding_hash,
        record.verifier_receipt_hash, record.observed_verdict, record.semantic_result_hash, record.execution_status, ())
    assert false.validate()
    assert not validate_execution_record(false, receipt=outcome.receipt, subject=subject, request=request,
                                         binding=plan.selected_bindings[0], descriptor=descriptor)


def test_differential_execution_uses_only_the_frozen_qualified_reference():
    d = runpy.run_path("tests/genesis/test_m6a2_differential.py")
    claim, descriptor = d["differential_claim"](), d["descriptor"]()
    cases = (
        d["case"](claim, case_id="truth", case_class=d["ReliabilityCaseClass"].TRUE_CASE,
                  expected_verdict=ReceiptStatus.PASS, candidate_name="two", reference_name="two"),
        d["case"](claim, case_id="mutant", case_class=d["ReliabilityCaseClass"].MUTANT,
                  expected_verdict=ReceiptStatus.FAIL, candidate_name="three", reference_name="two"),
        d["case"](claim, case_id="replay", case_class=d["ReliabilityCaseClass"].REPLAY,
                  expected_verdict=ReceiptStatus.PASS, candidate_name="two-replay", reference_name="two"),
    )
    campaign, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6b1-differential-campaign", descriptor=descriptor,
        implementation_identity_hash=descriptor.implementation_identity_hash, cases=cases,
        executions={cases[0].case_hash: d["execution"](claim, cases[0], d["times_two"], d["times_two"], "two"),
                    cases[1].case_hash: d["execution"](claim, cases[1], d["times_three"], d["times_two"], "two"),
                    cases[2].case_hash: d["execution"](claim, cases[2], d["times_two"], d["times_two"], "two")},
        campaign_policy_hash=d["h"]("m6b1-policy"))
    ref_identity = d["h"](("reference", "two"))
    reference = ReferenceDescriptor("two", "m6b1", "1", ref_identity, d["h"]("ref-impl"), d["h"]("ref-source"),
        d["h"]("ref-provenance"), "fixture", (claim.claim_type.value,), (canonical_sha256(claim.domain),))
    policy = ReferenceQualificationPolicy("m6b1", "1", ("fixture",), True, True, "exact-domain")
    registry = ReferenceRegistry(); registry.register(reference)
    qualification = qualify_reference(reference, policy, receipt_id="m6b1-reference")
    reference_binding = QualifiedReferenceBinding("two", "1", reference.descriptor_hash, ref_identity,
        qualification.receipt_hash, claim.claim_hash, canonical_sha256(claim.domain))
    verifier_registry = VerifierRegistry(); verifier_registry.register(descriptor)
    graph = VerifierDependencyGraph(); graph.add(descriptor)
    requirement = FederatedVerificationRequirement("differential", "differential", (AuthorityClass.DIFFERENTIAL,),
        (VerifierKind.DIFFERENTIAL,), 1, 1, False)
    verification_plan = VerificationPlan("m6b1-differential", claim.claim_hash,
        (VerificationObligation("differential", "differential", "candidate", "DIFFERENTIAL",
                               (descriptor.verifier_id,), "fail"),), {}, {})
    integrity = VerifierIntegrityReceipt("m6b1-integrity", descriptor.descriptor_hash,
        descriptor.implementation_identity_hash, descriptor.implementation_identity_hash,
        descriptor.dependency_manifest_hash, profile.profile_hash, IntegrityStatus.PASS, ())
    router = VerifierRouter(claim=claim, verification_plan=verification_plan, requirements=(requirement,),
        registry=verifier_registry, dependency_graph=graph, reliability_profiles=(profile,), campaign_receipts=(campaign,),
        integrity_receipts=(integrity,), qualified_reference_bindings=(reference_binding,), reference_registry=registry,
        qualification_receipts=(qualification,), qualification_policies=(policy,))
    plan = router.route(); binding = plan.selected_bindings[0]
    context = {"claim": claim, "candidate_identity_hash": d["h"]("m6b1-differential-candidate"),
               "reference_identity_hash": ref_identity, "plan_hash": plan.plan_hash, "snapshot_hash": d["h"]("snapshot")}
    context["context_hash"] = canonical_execution_context_hash(claim.claim_hash, context["candidate_identity_hash"], context)
    subject = ExecutionSubjectBinding(claim.claim_hash, context["candidate_identity_hash"], canonical_sha256(claim.domain), context["context_hash"])
    request = PlannedExecutionRequest(plan.plan_hash, "differential", requirement.requirement_hash, binding.binding_hash, subject.subject_hash)
    verifier = DifferentialVerifier(d["times_two"], reference_identity_hash=ref_identity)
    outcome = PlanBoundExecutionKernel(router).execute(federation_plan=plan, request=request, subject=subject,
        descriptor=descriptor, verifier=verifier, claim=claim, candidate=d["times_two"], context=context,
        qualified_reference_binding=reference_binding)
    assert outcome.admission.status is ExecutionAdmissionStatus.ADMITTED and outcome.receipt.status is ReceiptStatus.PASS
    substitute = QualifiedReferenceBinding("other", "1", reference.descriptor_hash, d["h"]("other-reference"),
        qualification.receipt_hash, claim.claim_hash, canonical_sha256(claim.domain))
    calls = {"count": 0}; original = verifier.verify
    def counted(*args): calls["count"] += 1; return original(*args)
    verifier.verify = counted
    rejected = PlanBoundExecutionKernel(router).execute(federation_plan=plan, request=request, subject=subject,
        descriptor=descriptor, verifier=verifier, claim=claim, candidate=d["times_two"], context=context,
        qualified_reference_binding=substitute)
    assert rejected.admission.status is ExecutionAdmissionStatus.REJECTED_BINDING_MISMATCH and calls["count"] == 0


def test_property_and_heuristic_real_execution_remain_plan_bound():
    p = runpy.run_path("tests/genesis/test_m6a2_property.py")
    property_spec, property_claim = p["spec"](p["PropertyKind"].NON_NEGATIVE), None
    property_claim = p["property_claim"](property_spec)
    pcases = (
        p["reliability_case"](property_claim, property_spec, case_id="truth", case_class=p["ReliabilityCaseClass"].TRUE_CASE, expected_verdict=ReceiptStatus.PASS, candidate_name="square"),
        p["reliability_case"](property_claim, property_spec, case_id="mutant", case_class=p["ReliabilityCaseClass"].MUTANT, expected_verdict=ReceiptStatus.FAIL, candidate_name="identity"),
        p["reliability_case"](property_claim, property_spec, case_id="replay", case_class=p["ReliabilityCaseClass"].REPLAY, expected_verdict=ReceiptStatus.PASS, candidate_name="square-replay"),
    )
    property_descriptor = p["descriptor"]()
    pcampaign, pprofile = VerifierReliabilityCampaign().run(receipt_id="m6b1-property", descriptor=property_descriptor,
        implementation_identity_hash=property_descriptor.implementation_identity_hash, cases=pcases,
        executions={pcases[0].case_hash: (p["PropertyVerifier"](property_spec), p["square"], p["context"](property_claim, property_spec, "square")),
                    pcases[1].case_hash: (p["PropertyVerifier"](property_spec), p["identity"], p["context"](property_claim, property_spec, "identity")),
                    pcases[2].case_hash: (p["PropertyVerifier"](property_spec), p["square"], p["context"](property_claim, property_spec, "square-replay"))}, campaign_policy_hash=p["h"]("m6b1"))
    router = generic_router(property_claim, property_descriptor, pcampaign, pprofile, "property", AuthorityClass.PROPERTY, VerifierKind.PROPERTY)
    plan = router.route(); context, subject, request = planned_context(router, plan, property_claim, p["h"]("subject"), {"property_spec_hash": property_spec.spec_hash})
    outcome = PlanBoundExecutionKernel(router).execute(federation_plan=plan, request=request, subject=subject,
        descriptor=property_descriptor, verifier=p["PropertyVerifier"](property_spec), claim=property_claim,
        candidate=p["square"], context=context)
    assert outcome.admission.status is ExecutionAdmissionStatus.ADMITTED and outcome.receipt.status is ReceiptStatus.PASS

    h = runpy.run_path("tests/genesis/test_m6a2_heuristic.py")
    policy = h["policy"](); heuristic_claim = h["heuristic_claim"](policy); heuristic_descriptor = h["descriptor"]()
    hcases = (
        h["reliability_case"](heuristic_claim, policy, case_id="truth", case_class=h["ReliabilityCaseClass"].TRUE_CASE, expected_verdict=ReceiptStatus.PASS, candidate_name="plus"),
        h["reliability_case"](heuristic_claim, policy, case_id="mutant", case_class=h["ReliabilityCaseClass"].MUTANT, expected_verdict=ReceiptStatus.FAIL, candidate_name="mutant"),
        h["reliability_case"](heuristic_claim, policy, case_id="replay", case_class=h["ReliabilityCaseClass"].REPLAY, expected_verdict=ReceiptStatus.PASS, candidate_name="plus-replay"),
    )
    hcampaign, hprofile = VerifierReliabilityCampaign().run(receipt_id="m6b1-heuristic", descriptor=heuristic_descriptor,
        implementation_identity_hash=heuristic_descriptor.implementation_identity_hash, cases=hcases,
        executions={hcases[0].case_hash: (h["HeuristicVerifier"](policy), h["plus_one"], h["context"](heuristic_claim, policy, "plus")),
                    hcases[1].case_hash: (h["HeuristicVerifier"](policy), h["probe_mutant"], h["context"](heuristic_claim, policy, "mutant")),
                    hcases[2].case_hash: (h["HeuristicVerifier"](policy), h["plus_one"], h["context"](heuristic_claim, policy, "plus-replay"))}, campaign_policy_hash=h["h"]("m6b1"))
    router = generic_router(heuristic_claim, heuristic_descriptor, hcampaign, hprofile, "heuristic", AuthorityClass.HEURISTIC, VerifierKind.HEURISTIC)
    plan = router.route(); context, subject, request = planned_context(router, plan, heuristic_claim, h["h"]("subject"), {"heuristic_policy_hash": policy.policy_hash})
    outcome = PlanBoundExecutionKernel(router).execute(federation_plan=plan, request=request, subject=subject,
        descriptor=heuristic_descriptor, verifier=h["HeuristicVerifier"](policy), claim=heuristic_claim,
        candidate=h["plus_one"], context=context)
    assert outcome.admission.status is ExecutionAdmissionStatus.ADMITTED and outcome.receipt.status is ReceiptStatus.PASS
