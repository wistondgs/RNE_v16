"""M6A-2P: sealed finite-domain property verification."""

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
from lab.genesis.verifiers.differential import DifferentialVerifier
from lab.genesis.verifiers.property import PropertyKind, PropertySpec, PropertyVerifier
from lab.genesis.verifiers.reliability import ReliabilityStatus
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCase,
    ReliabilityCaseClass,
    VerifierReliabilityCampaign,
    canonical_execution_context_hash as m6a1_context_hash,
    validate_profile_binding,
)


def h(value: object) -> str:
    return canonical_sha256({"m6a2p_test": value})


def domain(*, lower: int = -10, upper: int = 10) -> dict[str, int | str]:
    return {"kind": "integer_range", "min": lower, "max": upper}


def spec(
    property_kind: PropertyKind,
    *,
    parameters: Mapping[str, Any] | None = None,
    checked_domain: Mapping[str, Any] | None = None,
) -> PropertySpec:
    return PropertySpec.for_domain(
        property_id=f"m6a2p-{property_kind.value.lower()}",
        schema_version="genesis.m6a2p",
        property_kind=property_kind,
        parameters=parameters or {},
        domain=checked_domain or domain(),
    )


def property_claim(
    property_spec: PropertySpec, *, checked_domain: Mapping[str, Any] | None = None
) -> TypedClaim:
    return TypedClaim(
        claim_id=f"m6a2p-claim-{property_spec.property_id}",
        schema_version="genesis.m6a2p",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={
            "relation": "property_check",
            "property_spec_hash": property_spec.spec_hash,
        },
        assumptions=(),
        domain=checked_domain or domain(),
        budget={},
        falsifiers=("counterexample",),
        obligations=("property",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )


def context(
    claim: TypedClaim, property_spec: PropertySpec, candidate_name: str
) -> dict[str, Any]:
    candidate_identity_hash = h(("candidate", candidate_name))
    value: dict[str, Any] = {
        "claim": claim,
        "plan_hash": h("plan"),
        "snapshot_hash": h("snapshot"),
        "candidate_identity_hash": candidate_identity_hash,
        "property_spec_hash": property_spec.spec_hash,
    }
    value["context_hash"] = canonical_execution_context_hash(
        claim.claim_hash, candidate_identity_hash, value
    )
    return value


def descriptor() -> VerifierDescriptor:
    identity = PropertyVerifier.implementation_identity()
    return VerifierDescriptor(
        verifier_id=PropertyVerifier.verifier_id,
        schema_version="genesis.m6a2p",
        verifier_version=PropertyVerifier.verifier_version,
        verifier_kind=VerifierKind.PROPERTY,
        authority_class=AuthorityClass.PROPERTY,
        sovereignty=VerifierSovereignty.SUPPORTING,
        supported_claim_types=(ClaimType.EXACT_FUNCTION.value,),
        supported_obligation_kinds=("property",),
        implementation_identity_hash=identity.identity_hash,
        dependency_manifest_hash=h("property-no-external-dependencies"),
        cost_class="finite-exhaustive",
        deterministic=True,
    )


def square(value: int) -> int:
    return value * value


def identity(value: int) -> int:
    return value


def times_two(value: int) -> int:
    return 2 * value


def local_inversion(value: int) -> int:
    return -100 if value == 1 else 2 * value


def bounded_candidate(value: int) -> int:
    return value + 10


def out_of_bounds_candidate(value: int) -> int:
    return 101 if value == 10 else value + 10


def test_context_hash_extraction_is_bit_for_bit_compatible_with_m6a1() -> None:
    historical_context = {
        "claim": "excluded-claim-object",
        "claim_hash": "excluded-claim-hash",
        "candidate_identity_hash": "excluded-candidate-hash",
        "context_hash": "excluded-context-hash",
        "plan_hash": "plan-v1",
        "snapshot_hash": "snapshot-v1",
        "property_spec_hash": "property-spec-v1",
        "reference_identity_hash": "reference-v1",
    }
    expected = "e5db76f7a2a31bad313d187d7dcdcfe204f2013ad63118fe6911d79f64f9951c"

    assert canonical_execution_context_hash(
        "claim-v1", "candidate-v1", historical_context
    ) == expected
    assert m6a1_context_hash("claim-v1", "candidate-v1", historical_context) == expected


def test_property_spec_is_sealed_and_implementation_is_supporting() -> None:
    property_spec = spec(PropertyKind.BOUNDED_RANGE, parameters={"lower": 0, "upper": 100})
    identity_a = PropertyVerifier.implementation_identity()
    identity_b = PropertyVerifier.implementation_identity()

    assert property_spec.validate()
    assert property_spec.parameters_hash == canonical_sha256({"lower": 0, "upper": 100})
    assert identity_a == identity_b
    assert descriptor().implementation_identity_hash == identity_a.identity_hash
    assert descriptor().sovereignty is VerifierSovereignty.SUPPORTING


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("property_kind", PropertyKind.BOUNDED_RANGE),
        ("domain_hash", h("forged-domain")),
        ("parameters", {"lower": 0, "upper": 1}),
    ),
)
def test_property_spec_tampering_invalidates_its_seal(
    field: str, forged_value: object
) -> None:
    property_spec = spec(PropertyKind.NON_NEGATIVE)
    original_hash = property_spec.spec_hash
    object.__setattr__(property_spec, field, forged_value)

    assert property_spec.spec_hash == original_hash
    assert not property_spec.validate()


def test_non_negative_pass_and_coverage_are_derived_from_execution() -> None:
    property_spec = spec(PropertyKind.NON_NEGATIVE)
    claim = property_claim(property_spec)
    receipt = PropertyVerifier(property_spec).verify(
        claim, square, context(claim, property_spec, "square")
    )

    assert receipt.status is ReceiptStatus.PASS
    assert receipt.coverage == {"evaluated_inputs": 21, "declared_inputs": 21}
    assert receipt.cost == {"evaluations": 21}
    assert receipt.evidence["property_spec_hash"] == property_spec.spec_hash


def test_non_negative_failure_has_reproducible_counterexample() -> None:
    property_spec = spec(PropertyKind.NON_NEGATIVE)
    claim = property_claim(property_spec)
    receipt = PropertyVerifier(property_spec).verify(
        claim, identity, context(claim, property_spec, "identity")
    )

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.counterexamples[0] == {"input": -10, "output": -10}


def test_monotonic_pass_does_not_assert_functional_equivalence() -> None:
    property_spec = spec(PropertyKind.MONOTONIC_NON_DECREASING)
    claim = property_claim(property_spec)
    receipt = PropertyVerifier(property_spec).verify(
        claim, times_two, context(claim, property_spec, "times-two")
    )

    assert receipt.status is ReceiptStatus.PASS
    assert receipt.evidence["property_kind"] == PropertyKind.MONOTONIC_NON_DECREASING.value
    assert "reference_identity_hash" not in receipt.evidence


def test_monotonic_failure_identifies_the_local_order_inversion() -> None:
    property_spec = spec(PropertyKind.MONOTONIC_NON_DECREASING)
    claim = property_claim(property_spec)
    receipt = PropertyVerifier(property_spec).verify(
        claim, local_inversion, context(claim, property_spec, "local-inversion")
    )

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.counterexamples[0] == {
        "left_input": 0,
        "left_output": 0,
        "right_input": 1,
        "right_output": -100,
    }


def test_bounded_range_pass_and_failure_bind_declared_bounds() -> None:
    property_spec = spec(
        PropertyKind.BOUNDED_RANGE, parameters={"lower": 0, "upper": 100}
    )
    claim = property_claim(property_spec)
    verifier = PropertyVerifier(property_spec)
    passing = verifier.verify(
        claim, bounded_candidate, context(claim, property_spec, "bounded")
    )
    failing = verifier.verify(
        claim, out_of_bounds_candidate, context(claim, property_spec, "out-of-bounds")
    )

    assert passing.status is ReceiptStatus.PASS
    assert failing.status is ReceiptStatus.FAIL
    assert failing.counterexamples == (
        {"input": 10, "output": 101, "lower": 0, "upper": 100},
    )
    assert failing.evidence["parameters_hash"] == property_spec.parameters_hash


def test_claim_candidate_domain_context_and_property_bindings_reject_mismatch() -> None:
    property_spec = spec(PropertyKind.NON_NEGATIVE)
    claim = property_claim(property_spec)
    subject = PropertyVerifier(property_spec)
    valid = context(claim, property_spec, "square")
    wrong_claim = dict(valid)
    wrong_claim["claim"] = property_claim(property_spec, checked_domain=domain(lower=-9))
    wrong_candidate = dict(valid)
    wrong_candidate.pop("candidate_identity_hash")
    wrong_domain_claim = property_claim(property_spec, checked_domain=domain(lower=-9))
    wrong_context = dict(valid)
    wrong_context["plan_hash"] = h("substituted-plan")
    wrong_property = dict(valid)
    wrong_property["property_spec_hash"] = h("substituted-property")

    assert subject.verify(claim, square, wrong_claim).evidence["reason"] == "claim_context_mismatch"
    assert subject.verify(claim, square, wrong_candidate).evidence["reason"] == "candidate_identity_hash_missing"
    assert subject.verify(wrong_domain_claim, square, context(wrong_domain_claim, property_spec, "square")).evidence[
        "reason"
    ] == "property_domain_mismatch"
    assert subject.verify(claim, square, wrong_context).evidence["reason"] == "context_hash_invalid"
    assert subject.verify(claim, square, wrong_property).evidence["reason"] == "context_property_spec_mismatch"


def test_unknown_and_error_are_not_reinterpreted_as_pass() -> None:
    property_spec = spec(PropertyKind.NON_NEGATIVE)
    claim = property_claim(property_spec)
    unsupported = replace(claim, properties={"relation": "unsupported"})

    unknown = PropertyVerifier(property_spec).verify(
        unsupported, square, context(unsupported, property_spec, "square")
    )
    error = PropertyVerifier(property_spec).verify(
        claim, "not-callable", context(claim, property_spec, "not-callable")
    )

    assert unknown.status is ReceiptStatus.UNKNOWN
    assert error.status is ReceiptStatus.ERROR


def test_unsupported_domain_remains_unknown() -> None:
    unsupported_domain = {"kind": "opaque_finite_set", "members": (1, 2)}
    property_spec = spec(PropertyKind.NON_NEGATIVE, checked_domain=unsupported_domain)
    claim = property_claim(property_spec, checked_domain=unsupported_domain)

    receipt = PropertyVerifier(property_spec).verify(
        claim, square, context(claim, property_spec, "square")
    )

    assert receipt.status is ReceiptStatus.UNKNOWN
    assert receipt.evidence["reason"] == "unsupported_finite_domain"


def reliability_case(
    claim: TypedClaim,
    property_spec: PropertySpec,
    *,
    case_id: str,
    case_class: ReliabilityCaseClass,
    expected_verdict: ReceiptStatus,
    candidate_name: str,
) -> ReliabilityCase:
    case_context = context(claim, property_spec, candidate_name)
    return ReliabilityCase(
        case_id=case_id,
        schema_version="genesis.m6a2p",
        claim_hash=claim.claim_hash,
        case_class=case_class,
        expected_verdict=expected_verdict,
        candidate_identity_hash=case_context["candidate_identity_hash"],
        reference_identity_hash=None,
        domain_hash=canonical_sha256(claim.domain),
        context_hash=case_context["context_hash"],
        source_provenance_hash=h("external-property-ground-truth-v1"),
    )


class BlindPropertyVerifier:
    """Controlled defective double proving M6A-1 derives degradation."""

    verifier_id = PropertyVerifier.verifier_id
    verifier_version = PropertyVerifier.verifier_version

    def __init__(self, property_spec: PropertySpec) -> None:
        self._actual = PropertyVerifier(property_spec)

    def verify(
        self, claim: TypedClaim, candidate: Any, execution_context: Mapping[str, Any]
    ) -> VerifierReceipt:
        actual = self._actual.verify(claim, candidate, execution_context)
        return replace(
            actual,
            status=ReceiptStatus.PASS,
            evidence={"reason": "blind-property-test-double"},
            counterexamples=(),
        )


def test_real_property_campaign_is_characterized_and_replay_consistent() -> None:
    non_negative = spec(PropertyKind.NON_NEGATIVE)
    monotonic = spec(PropertyKind.MONOTONIC_NON_DECREASING)
    bounded = spec(PropertyKind.BOUNDED_RANGE, parameters={"lower": 0, "upper": 100})
    claim_non_negative = property_claim(non_negative)
    claim_monotonic = property_claim(monotonic)
    claim_bounded = property_claim(bounded)
    cases = (
        reliability_case(
            claim_non_negative,
            non_negative,
            case_id="square-truth",
            case_class=ReliabilityCaseClass.TRUE_CASE,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="square",
        ),
        reliability_case(
            claim_monotonic,
            monotonic,
            case_id="times-two-truth",
            case_class=ReliabilityCaseClass.TRUE_CASE,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="times-two",
        ),
        reliability_case(
            claim_non_negative,
            non_negative,
            case_id="identity-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="identity",
        ),
        reliability_case(
            claim_monotonic,
            monotonic,
            case_id="inversion-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="local-inversion",
        ),
        reliability_case(
            claim_bounded,
            bounded,
            case_id="bounds-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="out-of-bounds",
        ),
        reliability_case(
            claim_non_negative,
            non_negative,
            case_id="square-replay",
            case_class=ReliabilityCaseClass.REPLAY,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="square",
        ),
    )
    executions = {
        cases[0].case_hash: (
            PropertyVerifier(non_negative),
            square,
            context(claim_non_negative, non_negative, "square"),
        ),
        cases[1].case_hash: (
            PropertyVerifier(monotonic),
            times_two,
            context(claim_monotonic, monotonic, "times-two"),
        ),
        cases[2].case_hash: (
            PropertyVerifier(non_negative),
            identity,
            context(claim_non_negative, non_negative, "identity"),
        ),
        cases[3].case_hash: (
            PropertyVerifier(monotonic),
            local_inversion,
            context(claim_monotonic, monotonic, "local-inversion"),
        ),
        cases[4].case_hash: (
            PropertyVerifier(bounded),
            out_of_bounds_candidate,
            context(claim_bounded, bounded, "out-of-bounds"),
        ),
        cases[5].case_hash: (
            PropertyVerifier(non_negative),
            square,
            context(claim_non_negative, non_negative, "square"),
        ),
    }
    property_descriptor = descriptor()

    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6a2p-real-campaign",
        descriptor=property_descriptor,
        implementation_identity_hash=property_descriptor.implementation_identity_hash,
        cases=cases,
        executions=executions,
        campaign_policy_hash=h("m6a2p-reliability-policy"),
    )

    assert receipt.validate()
    assert receipt.correct_cases == 2
    assert receipt.mutation_cases == receipt.mutations_detected == 3
    assert receipt.replay_cases == receipt.replay_consistent == 1
    assert profile.status is ReliabilityStatus.CHARACTERIZED
    assert property_descriptor.sovereignty is VerifierSovereignty.SUPPORTING
    assert validate_profile_binding(
        profile,
        receipt,
        property_descriptor.descriptor_hash,
        property_descriptor.implementation_identity_hash,
    )


def test_blind_property_campaign_is_degraded_from_observed_mutation_miss() -> None:
    non_negative = spec(PropertyKind.NON_NEGATIVE)
    claim = property_claim(non_negative)
    truth = reliability_case(
        claim,
        non_negative,
        case_id="square-truth",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="square",
    )
    mutant = reliability_case(
        claim,
        non_negative,
        case_id="identity-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="identity",
    )
    blind = BlindPropertyVerifier(non_negative)
    property_descriptor = descriptor()

    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6a2p-blind-campaign",
        descriptor=property_descriptor,
        implementation_identity_hash=property_descriptor.implementation_identity_hash,
        cases=(truth, mutant),
        executions={
            truth.case_hash: (blind, square, context(claim, non_negative, "square")),
            mutant.case_hash: (blind, identity, context(claim, non_negative, "identity")),
        },
        campaign_policy_hash=h("m6a2p-reliability-policy"),
    )

    assert receipt.mutation_cases == 1
    assert receipt.mutations_detected == 0
    assert profile.status is ReliabilityStatus.DEGRADED
    assert "required_mutation_missed" in profile.reason_codes


def test_property_and_differential_receipts_prove_distinct_claims() -> None:
    monotonic = spec(PropertyKind.MONOTONIC_NON_DECREASING)
    property_claim_for_two_x = property_claim(monotonic)
    property_receipt = PropertyVerifier(monotonic).verify(
        property_claim_for_two_x,
        times_two,
        context(property_claim_for_two_x, monotonic, "times-two"),
    )
    differential_claim = TypedClaim(
        claim_id="m6a2p-differential-two-x",
        schema_version="genesis.m6a2p",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={"relation": "reference_equivalence"},
        assumptions=(),
        domain=domain(),
        budget={},
        falsifiers=("counterexample",),
        obligations=("differential",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )
    reference_identity_hash = h(("reference", "times-two"))
    differential_context: dict[str, Any] = {
        "claim": differential_claim,
        "plan_hash": h("plan"),
        "snapshot_hash": h("snapshot"),
        "candidate_identity_hash": h(("candidate", "times-two")),
        "reference_identity_hash": reference_identity_hash,
    }
    differential_context["context_hash"] = canonical_execution_context_hash(
        differential_claim.claim_hash,
        differential_context["candidate_identity_hash"],
        differential_context,
    )
    differential_receipt = DifferentialVerifier(
        times_two, reference_identity_hash=reference_identity_hash
    ).verify(differential_claim, times_two, differential_context)

    assert property_receipt.status is differential_receipt.status is ReceiptStatus.PASS
    assert property_receipt.claim_hash != differential_receipt.claim_hash
    assert property_receipt.evidence["property_kind"] == "MONOTONIC_NON_DECREASING"
    assert "reference_identity_hash" not in property_receipt.evidence
    assert differential_receipt.evidence["relation"] == "reference_equivalence"
    assert differential_receipt.evidence["reference_identity_hash"] == reference_identity_hash
