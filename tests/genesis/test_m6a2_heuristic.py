"""M6A-2H: deterministic partial coverage stays non-sovereign."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

import pytest

from lab.genesis.contracts.claims import ChangeClass, ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers.bindings import canonical_execution_context_hash
from lab.genesis.verifiers.descriptor import (
    AuthorityClass,
    VerifierDescriptor,
    VerifierKind,
    VerifierSovereignty,
)
from lab.genesis.verifiers.exact import ExactVerifier
from lab.genesis.verifiers.heuristic import HeuristicPolicySpec, HeuristicVerifier
from lab.genesis.verifiers.reliability import ReliabilityStatus
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCase,
    ReliabilityCaseClass,
    VerifierReliabilityCampaign,
    validate_profile_binding,
)


def h(value: object) -> str:
    return canonical_sha256({"m6a2h_test": value})


def domain(*, lower: int = -10, upper: int = 10) -> dict[str, int | str]:
    return {"kind": "integer_range", "min": lower, "max": upper}


def policy(*, checked_domain: Mapping[str, Any] | None = None) -> HeuristicPolicySpec:
    return HeuristicPolicySpec.for_domain(
        policy_id="m6a2h-first-middle-last",
        schema_version="genesis.m6a2h",
        domain=checked_domain or domain(),
    )


def heuristic_claim(
    heuristic_policy: HeuristicPolicySpec,
    *,
    checked_domain: Mapping[str, Any] | None = None,
) -> TypedClaim:
    return TypedClaim(
        claim_id="m6a2h-plus-one",
        schema_version="genesis.m6a2h",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={
            "relation": "output_eq_input_plus",
            "delta": 1,
            "heuristic_policy_hash": heuristic_policy.policy_hash,
        },
        assumptions=(),
        domain=checked_domain or domain(),
        budget={},
        falsifiers=("counterexample",),
        obligations=("heuristic",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )


def context(
    claim: TypedClaim, heuristic_policy: HeuristicPolicySpec, candidate_name: str
) -> dict[str, Any]:
    candidate_identity_hash = h(("candidate", candidate_name))
    value: dict[str, Any] = {
        "claim": claim,
        "plan_hash": h("plan"),
        "snapshot_hash": h("snapshot"),
        "candidate_identity_hash": candidate_identity_hash,
        "heuristic_policy_hash": heuristic_policy.policy_hash,
    }
    value["context_hash"] = canonical_execution_context_hash(
        claim.claim_hash, candidate_identity_hash, value
    )
    return value


def descriptor() -> VerifierDescriptor:
    identity = HeuristicVerifier.implementation_identity()
    return VerifierDescriptor(
        verifier_id=HeuristicVerifier.verifier_id,
        schema_version="genesis.m6a2h",
        verifier_version=HeuristicVerifier.verifier_version,
        verifier_kind=VerifierKind.HEURISTIC,
        authority_class=AuthorityClass.HEURISTIC,
        sovereignty=VerifierSovereignty.NON_SOVEREIGN,
        supported_claim_types=(ClaimType.EXACT_FUNCTION.value,),
        supported_obligation_kinds=("heuristic",),
        implementation_identity_hash=identity.identity_hash,
        dependency_manifest_hash=h("heuristic-no-external-dependencies"),
        cost_class="deterministic-probes",
        deterministic=True,
    )


def plus_one(value: int) -> int:
    return value + 1


def probe_mutant(value: int) -> int:
    return value + 2 if value == 0 else value + 1


def blind_spot_mutant(value: int) -> int:
    return value + 2 if value == 1 else value + 1


def test_policy_is_sealed_and_probe_selection_is_deterministic() -> None:
    first = policy()
    second = policy()
    first_verifier = HeuristicVerifier(first)
    second_verifier = HeuristicVerifier(second)

    assert first.validate() and second.validate()
    assert first.policy_hash == second.policy_hash
    assert first_verifier.probe_inputs(domain()) == (-10, 0, 10)
    assert first_verifier.probe_inputs(domain()) == second_verifier.probe_inputs(domain())
    assert first_verifier.implementation_identity() == second_verifier.implementation_identity()
    claim = heuristic_claim(first)
    execution_context = context(claim, first, "plus-one")
    first_receipt = first_verifier.verify(claim, plus_one, execution_context)
    second_receipt = second_verifier.verify(claim, plus_one, execution_context)
    assert first_receipt.evidence == second_receipt.evidence
    assert first_receipt.coverage == second_receipt.coverage
    assert first_receipt.receipt_hash == second_receipt.receipt_hash


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("policy_kind", "FORGED_POLICY_KIND"),
        ("domain_hash", h("forged-domain")),
        ("parameters", {"selection": "all_inputs"}),
    ),
)
def test_policy_tampering_invalidates_the_seal(field: str, forged_value: object) -> None:
    heuristic_policy = policy()
    original_hash = heuristic_policy.policy_hash
    object.__setattr__(heuristic_policy, field, forged_value)

    assert heuristic_policy.policy_hash == original_hash
    assert not heuristic_policy.validate()


def test_correct_candidate_passes_with_explicitly_partial_coverage() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    receipt = HeuristicVerifier(heuristic_policy).verify(
        claim, plus_one, context(claim, heuristic_policy, "plus-one")
    )

    assert receipt.status is ReceiptStatus.PASS
    assert receipt.coverage["declared_domain_size"] == 21
    assert receipt.coverage["probes_evaluated"] == 3
    assert receipt.coverage["probe_coverage"] == {"numerator": 3, "denominator": 21}
    assert receipt.evidence["full_domain_verified"] is False
    assert receipt.evidence["probe_coverage"] == {"numerator": 3, "denominator": 21}


def test_probe_mutant_fails_with_a_reproducible_counterexample() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    receipt = HeuristicVerifier(heuristic_policy).verify(
        claim, probe_mutant, context(claim, heuristic_policy, "probe-mutant")
    )

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.counterexamples == ({"input": 0, "expected": 1, "actual": 2},)


def test_blind_spot_pass_is_not_an_exact_proof() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    execution_context = context(claim, heuristic_policy, "blind-spot-mutant")

    heuristic = HeuristicVerifier(heuristic_policy).verify(
        claim, blind_spot_mutant, execution_context
    )
    exact = ExactVerifier().verify(claim, blind_spot_mutant, execution_context)

    assert 1 not in HeuristicVerifier(heuristic_policy).probe_inputs(claim.domain)
    assert heuristic.status is ReceiptStatus.PASS
    assert heuristic.evidence["full_domain_verified"] is False
    assert exact.status is ReceiptStatus.FAIL
    assert {item["input"] for item in exact.counterexamples} == {1}


def test_claim_candidate_domain_context_and_policy_bindings_reject_mismatch() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    subject = HeuristicVerifier(heuristic_policy)
    valid = context(claim, heuristic_policy, "plus-one")
    wrong_claim = dict(valid)
    wrong_claim["claim"] = heuristic_claim(heuristic_policy, checked_domain=domain(lower=-9))
    wrong_candidate = dict(valid)
    wrong_candidate.pop("candidate_identity_hash")
    wrong_domain_claim = heuristic_claim(heuristic_policy, checked_domain=domain(lower=-9))
    wrong_context = dict(valid)
    wrong_context["plan_hash"] = h("substituted-plan")
    wrong_policy = dict(valid)
    wrong_policy["heuristic_policy_hash"] = h("substituted-policy")

    assert subject.verify(claim, plus_one, wrong_claim).evidence["reason"] == "claim_context_mismatch"
    assert subject.verify(claim, plus_one, wrong_candidate).evidence["reason"] == "candidate_identity_hash_missing"
    assert subject.verify(wrong_domain_claim, plus_one, context(wrong_domain_claim, heuristic_policy, "plus-one")).evidence[
        "reason"
    ] == "policy_domain_mismatch"
    assert subject.verify(claim, plus_one, wrong_context).evidence["reason"] == "context_hash_invalid"
    assert subject.verify(claim, plus_one, wrong_policy).evidence["reason"] == "context_policy_mismatch"


def test_unknown_and_error_are_not_reinterpreted_as_pass() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    unsupported = replace(claim, properties={"relation": "unsupported"})

    unknown = HeuristicVerifier(heuristic_policy).verify(
        unsupported, plus_one, context(unsupported, heuristic_policy, "plus-one")
    )
    error = HeuristicVerifier(heuristic_policy).verify(
        claim, "not-callable", context(claim, heuristic_policy, "not-callable")
    )

    assert unknown.status is ReceiptStatus.UNKNOWN
    assert error.status is ReceiptStatus.ERROR


def reliability_case(
    claim: TypedClaim,
    heuristic_policy: HeuristicPolicySpec,
    *,
    case_id: str,
    case_class: ReliabilityCaseClass,
    expected_verdict: ReceiptStatus,
    candidate_name: str,
) -> ReliabilityCase:
    case_context = context(claim, heuristic_policy, candidate_name)
    return ReliabilityCase(
        case_id=case_id,
        schema_version="genesis.m6a2h",
        claim_hash=claim.claim_hash,
        case_class=case_class,
        expected_verdict=expected_verdict,
        candidate_identity_hash=case_context["candidate_identity_hash"],
        reference_identity_hash=None,
        domain_hash=canonical_sha256(claim.domain),
        context_hash=case_context["context_hash"],
        source_provenance_hash=h("external-heuristic-ground-truth-v1"),
    )


class BlindHeuristicVerifier:
    """Controlled defective double proving campaign-derived degradation."""

    verifier_id = HeuristicVerifier.verifier_id
    verifier_version = HeuristicVerifier.verifier_version

    def __init__(self, heuristic_policy: HeuristicPolicySpec) -> None:
        self._actual = HeuristicVerifier(heuristic_policy)

    def verify(
        self, claim: TypedClaim, candidate: Any, execution_context: Mapping[str, Any]
    ) -> VerifierReceipt:
        actual = self._actual.verify(claim, candidate, execution_context)
        return replace(
            actual,
            status=ReceiptStatus.PASS,
            evidence={"reason": "blind-heuristic-test-double"},
            counterexamples=(),
        )


def test_real_campaign_can_be_characterized_without_authority_promotion() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    cases = (
        reliability_case(
            claim,
            heuristic_policy,
            case_id="plus-one-truth",
            case_class=ReliabilityCaseClass.TRUE_CASE,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="plus-one",
        ),
        reliability_case(
            claim,
            heuristic_policy,
            case_id="probe-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="probe-mutant",
        ),
        reliability_case(
            claim,
            heuristic_policy,
            case_id="plus-one-replay",
            case_class=ReliabilityCaseClass.REPLAY,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="plus-one",
        ),
    )
    heuristic_descriptor = descriptor()
    executions = {
        cases[0].case_hash: (
            HeuristicVerifier(heuristic_policy),
            plus_one,
            context(claim, heuristic_policy, "plus-one"),
        ),
        cases[1].case_hash: (
            HeuristicVerifier(heuristic_policy),
            probe_mutant,
            context(claim, heuristic_policy, "probe-mutant"),
        ),
        cases[2].case_hash: (
            HeuristicVerifier(heuristic_policy),
            plus_one,
            context(claim, heuristic_policy, "plus-one"),
        ),
    }

    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6a2h-real-campaign",
        descriptor=heuristic_descriptor,
        implementation_identity_hash=heuristic_descriptor.implementation_identity_hash,
        cases=cases,
        executions=executions,
        campaign_policy_hash=h("m6a2h-reliability-policy"),
    )

    assert receipt.validate()
    assert receipt.mutation_cases == receipt.mutations_detected == 1
    assert receipt.replay_cases == receipt.replay_consistent == 1
    assert profile.status is ReliabilityStatus.CHARACTERIZED
    assert heuristic_descriptor.sovereignty is VerifierSovereignty.NON_SOVEREIGN
    assert validate_profile_binding(
        profile,
        receipt,
        heuristic_descriptor.descriptor_hash,
        heuristic_descriptor.implementation_identity_hash,
    )


def test_blind_spot_adversarial_mutation_degrades_campaign() -> None:
    heuristic_policy = policy()
    claim = heuristic_claim(heuristic_policy)
    truth = reliability_case(
        claim,
        heuristic_policy,
        case_id="plus-one-truth",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    # M6A-1's degradation policy treats a required blind-spot challenge as a
    # MUTANT, making the observed miss an authority-relevant campaign defect.
    blind_spot = reliability_case(
        claim,
        heuristic_policy,
        case_id="blind-spot-adversarial-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="blind-spot-mutant",
    )
    heuristic_descriptor = descriptor()

    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6a2h-blind-spot-campaign",
        descriptor=heuristic_descriptor,
        implementation_identity_hash=heuristic_descriptor.implementation_identity_hash,
        cases=(truth, blind_spot),
        executions={
            truth.case_hash: (
                HeuristicVerifier(heuristic_policy),
                plus_one,
                context(claim, heuristic_policy, "plus-one"),
            ),
            blind_spot.case_hash: (
                HeuristicVerifier(heuristic_policy),
                blind_spot_mutant,
                context(claim, heuristic_policy, "blind-spot-mutant"),
            ),
        },
        campaign_policy_hash=h("m6a2h-reliability-policy"),
    )

    assert receipt.mutation_cases == 1
    assert receipt.mutations_detected == 0
    assert profile.status is ReliabilityStatus.DEGRADED
    assert "required_mutation_missed" in profile.reason_codes
