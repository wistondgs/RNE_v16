"""M6A-3: routing is a sealed feasibility proof, never verifier execution."""
from __future__ import annotations

import runpy

from lab.genesis.causal.cfi import CFIReport, CFIStatus
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.contracts.verification import VerificationObligation, VerificationPlan
from lab.genesis.verifiers import (
    AuthorityClass, FederatedVerificationRequirement, FederationPlan, IntegrityStatus,
    QualifiedReferenceBinding, RequirementRoutingResult, RoutingStatus, SelectedVerifierBinding,
    VerifierDependencyGraph, VerifierIntegrityReceipt, VerifierKind, VerifierRegistry, VerifierRouter,
    validate_federation_plan, validate_presented_verifier_against_binding,
)

helpers = runpy.run_path("tests/genesis/test_m6a1_reliability_case.py")


def requirement(*, count: int = 1, independent: int = 1, cfi: bool = False):
    return FederatedVerificationRequirement(
        "router-requirement", "exact", (AuthorityClass.EXACT,),
        (VerifierKind.EXACT_EXECUTABLE,), count, independent, True, cfi,
    )


def prepared(*, descriptors=(), req=None, cfi_reports=()):
    claim, first, _cases, receipt, profile = helpers["minimally_complete_exact_campaign"]()
    descriptors = descriptors or (first,)
    registry, graph = VerifierRegistry(), VerifierDependencyGraph()
    for number, descriptor in enumerate(descriptors):
        registry.register(descriptor); graph.add(descriptor)
    reliability, campaign = profile, receipt
    integrity = VerifierIntegrityReceipt(
        "router-integrity", first.descriptor_hash, first.implementation_identity_hash,
        first.implementation_identity_hash, first.dependency_manifest_hash,
        reliability.profile_hash, IntegrityStatus.PASS, ())
    plan = VerificationPlan("router-plan", claim.claim_hash, (
        VerificationObligation("exact", "exact", "candidate", "EXACT",
                              tuple(x.verifier_id for x in descriptors), "fail"),), {}, {})
    return VerifierRouter(claim=claim, verification_plan=plan, requirements=(req or requirement(),), registry=registry,
                          dependency_graph=graph, reliability_profiles=(reliability,), campaign_receipts=(campaign,),
                          integrity_receipts=(integrity,), cfi_reports=cfi_reports), descriptors


def test_exact_route_is_plannable_and_binding_admits_only_exact_descriptor():
    router, (descriptor,) = prepared()
    plan = router.route()
    result = plan.routing_results[0]
    assert result.status is RoutingStatus.PLANNABLE
    assert validate_federation_plan(plan, router)
    binding = plan.selected_bindings[0]
    assert validate_presented_verifier_against_binding(descriptor, binding).value == "ADMISSIBLE"
    altered = helpers["exact_descriptor"](implementation_identity_hash=helpers["h"]("other"))
    assert validate_presented_verifier_against_binding(altered, binding).value == "INADMISSIBLE_FOR_PLAN"


def test_cfi_is_a_planning_prerequisite_not_a_verdict():
    router, _ = prepared(req=requirement(cfi=True))
    assert router.route().routing_results[0].status is RoutingStatus.INCOMPLETE_CFI
    report = CFIReport("router-cfi", (), (), (), "derived", (), CFIStatus.PASS)
    router, _ = prepared(req=requirement(cfi=True), cfi_reports=(report,))
    assert router.route().routing_results[0].status is RoutingStatus.PLANNABLE


def test_non_greedy_selection_uses_smallest_lexical_feasible_subset():
    first = helpers["exact_descriptor"](implementation_identity_hash=helpers["h"]("a"), verifier_id="a")
    second = helpers["exact_descriptor"](implementation_identity_hash=helpers["h"]("b"), verifier_id="b")
    third = helpers["exact_descriptor"](implementation_identity_hash=helpers["h"]("c"), verifier_id="c")
    router, descriptors = prepared(descriptors=(first, second, third), req=requirement(count=2, independent=2))
    # A is dependent on both; B+C is the only feasible pair.
    router.graph.edges.update({tuple(sorted((first.descriptor_hash, second.descriptor_hash))),
                               tuple(sorted((first.descriptor_hash, third.descriptor_hash)))})
    profile, integrity = router.profiles[0], router.integrities[0]
    router._profile = lambda _descriptor: profile
    router._integrity = lambda _descriptor, _profile: integrity
    selected = router.route().selected_bindings
    assert {x.verifier_id for x in selected} == {"b", "c"}


def test_shared_reference_identity_overrides_graph_independence():
    router, (a,) = prepared()
    b = helpers["exact_descriptor"](implementation_identity_hash=helpers["h"]("b"), verifier_id="b")
    router.registry.register(b); router.graph.add(b)
    ref = QualifiedReferenceBinding("ref", "1", helpers["h"]("d"), helpers["h"]("shared-ref"), helpers["h"]("q"), router.claim.claim_hash, canonical_sha256(router.claim.domain))
    assert not router._independent((a, None, None, ref), (b, None, None, ref))


def test_resealed_false_plan_is_rejected_by_semantic_rederivation():
    router, _ = prepared()
    plan = router.route()
    result = plan.routing_results[0]
    false_result = RequirementRoutingResult(result.requirement_id, result.requirement_hash, RoutingStatus.PLANNABLE, (), (), (router.graph.graph_hash,))
    false = FederationPlan(plan.schema_version, plan.claim_hash, plan.verification_plan_hash, plan.requirement_hashes,
                           (false_result,), (), plan.dependency_graph_hash, (), (), (), plan.cfi_report_hashes,
                           plan.selection_policy_hash)
    assert false.validate()
    assert not validate_federation_plan(false, router)
