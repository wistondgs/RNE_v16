"""Integrity and binding falsification tests for M6A-1 reliability evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab.genesis.contracts.receipts import ReceiptStatus
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers.reliability import ReliabilityStatus, VerifierReliabilityProfile
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCaseClass,
    validate_profile_binding,
)
from tests.genesis.test_m6a1_reliability_case import (
    exact_claim,
    exact_descriptor,
    execution,
    h,
    make_case,
    minimally_complete_exact_campaign,
    plus_one,
    run_campaign,
    x_plus_two,
)


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("observed_verdict", None),
        ("correct", False),
        ("semantic_result_hash", h("forged-semantic-result")),
        ("verifier_receipt_hash", h("forged-verifier-receipt")),
    ),
)
def test_case_result_tampering_invalidates_its_seal(
    field: str, forged_value: object
) -> None:
    _, _, _, receipt, _ = minimally_complete_exact_campaign()
    result = receipt.case_results[0]
    original_hash = result.result_hash
    if field == "observed_verdict":
        forged_value = (
            ReceiptStatus.FAIL
            if result.observed_verdict is ReceiptStatus.PASS
            else ReceiptStatus.PASS
        )

    object.__setattr__(result, field, forged_value)

    assert result.result_hash == original_hash
    assert result.result_hash != canonical_sha256(result.canonical_payload())
    assert not result.validate()
    assert not receipt.validate()


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("ordered_case_hashes", (h("forged-order"),)),
        ("case_results", ()),
        ("mutation_cases", 99),
        ("mutations_detected", 0),
        ("replay_consistent", 0),
        ("implementation_identity_hash", h("forged-implementation")),
    ),
)
def test_campaign_receipt_tampering_is_rejected(
    field: str, forged_value: object
) -> None:
    _, _, _, receipt, _ = minimally_complete_exact_campaign()
    original_hash = receipt.campaign_hash

    object.__setattr__(receipt, field, forged_value)

    assert receipt.campaign_hash == original_hash
    assert not receipt.validate()


def test_resealed_campaign_with_invented_mutation_counter_is_rejected() -> None:
    _, _, _, receipt, _ = minimally_complete_exact_campaign()

    # ``replace`` recomputes campaign_hash, so this is not merely stale-hash
    # detection.  The aggregate must still be derived from case results.
    forged = replace(receipt, mutation_cases=99)

    assert forged.campaign_hash != receipt.campaign_hash
    assert not forged.validate()


def test_profile_binds_to_the_exact_campaign_descriptor_and_implementation() -> None:
    claim, descriptor, cases, receipt_a, profile = minimally_complete_exact_campaign()
    executions = {
        case.case_hash: execution(
            case,
            claim,
            x_plus_two if case.case_class is ReliabilityCaseClass.MUTANT else plus_one,
        )[case.case_hash]
        for case in cases
    }
    receipt_b, _ = run_campaign(
        cases,
        executions,
        descriptor=descriptor,
        receipt_id="m6a1-separate-campaign",
    )
    other_descriptor = replace(descriptor, verifier_id="m6a1.other-exact")

    assert validate_profile_binding(
        profile,
        receipt_a,
        descriptor.descriptor_hash,
        descriptor.implementation_identity_hash,
    )
    assert not validate_profile_binding(
        profile,
        receipt_b,
        descriptor.descriptor_hash,
        descriptor.implementation_identity_hash,
    )
    assert not validate_profile_binding(
        profile,
        receipt_a,
        other_descriptor.descriptor_hash,
        descriptor.implementation_identity_hash,
    )
    assert not validate_profile_binding(
        profile,
        receipt_a,
        descriptor.descriptor_hash,
        h("substituted-implementation"),
    )


def test_profile_campaign_reference_tampering_is_rejected() -> None:
    claim, descriptor, cases, receipt_a, profile = minimally_complete_exact_campaign()
    receipt_b, _ = run_campaign(
        cases,
        {
            case.case_hash: execution(
                case,
                claim,
                x_plus_two if case.case_class is ReliabilityCaseClass.MUTANT else plus_one,
            )[case.case_hash]
            for case in cases
        },
        descriptor=descriptor,
        receipt_id="m6a1-profile-substitution-campaign",
    )
    original_hash = profile.profile_hash

    object.__setattr__(profile, "campaign_receipt_hash", receipt_b.campaign_hash)

    assert profile.profile_hash == original_hash
    assert not validate_profile_binding(
        profile,
        receipt_a,
        descriptor.descriptor_hash,
        descriptor.implementation_identity_hash,
    )


def test_resealed_profile_with_invented_truth_counts_is_not_campaign_derived() -> None:
    _, descriptor, _, receipt, profile = minimally_complete_exact_campaign()

    # This keeps profile-local arithmetic valid (0 + 1 == one truth case) and
    # recomputes profile_hash.  Only reconstruction from the receipt exposes it.
    forged = replace(profile, correct_cases=0, incorrect_cases=1)

    assert forged.profile_hash != profile.profile_hash
    assert forged.validate()
    assert not validate_profile_binding(
        forged,
        receipt,
        descriptor.descriptor_hash,
        descriptor.implementation_identity_hash,
    )


@pytest.mark.parametrize(
    "status", (ReliabilityStatus.CHARACTERIZED, ReliabilityStatus.DEGRADED)
)
def test_conclusive_profile_cannot_be_constructed_without_campaign_reference(
    status: ReliabilityStatus,
) -> None:
    descriptor = exact_descriptor()

    with pytest.raises(ValueError, match="campaign"):
        VerifierReliabilityProfile(
            profile_id="manually-labeled-profile",
            verifier_descriptor_hash=descriptor.descriptor_hash,
            domain_id="campaign",
            truth_known_cases=1,
            correct_cases=1,
            incorrect_cases=0,
            unknown_cases=0,
            error_cases=0,
            mutation_cases=1,
            mutations_detected=1,
            replay_cases=2,
            replay_consistent=2,
            adversarial_cases=0,
            adversarial_detected=0,
            status=status,
        )


def test_campaign_rejects_substituted_implementation_identity() -> None:
    claim = exact_claim()
    descriptor = exact_descriptor()
    case = make_case(
        claim,
        case_id="implementation-binding",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )

    with pytest.raises(ValueError, match="implementation"):
        run_campaign(
            (case,),
            execution(case, claim, plus_one),
            descriptor=descriptor,
            implementation_identity_hash=h("substituted-implementation"),
        )
