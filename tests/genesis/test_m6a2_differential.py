"""M6A-2D: finite-domain differential verification and characterization."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

import pytest

from lab.genesis.contracts.claims import ChangeClass, ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers.descriptor import (
    AuthorityClass,
    VerifierDescriptor,
    VerifierKind,
    VerifierSovereignty,
)
from lab.genesis.verifiers.differential import DifferentialVerifier
from lab.genesis.verifiers.exact import ExactVerifier
from lab.genesis.verifiers.reliability import ReliabilityStatus
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCase,
    ReliabilityCaseClass,
    VerifierReliabilityCampaign,
    canonical_execution_context_hash,
    validate_profile_binding,
)


def h(value: object) -> str:
    return canonical_sha256({"m6a2d_test": value})


def differential_claim(*, lower: int = -10, upper: int = 10) -> TypedClaim:
    return TypedClaim(
        claim_id="m6a2d-reference-equivalence",
        schema_version="genesis.m6a2d",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={"relation": "reference_equivalence"},
        assumptions=(),
        domain={"kind": "integer_range", "min": lower, "max": upper},
        budget={},
        falsifiers=("counterexample",),
        obligations=("differential",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )


def descriptor() -> VerifierDescriptor:
    identity = DifferentialVerifier.implementation_identity()
    return VerifierDescriptor(
        verifier_id=DifferentialVerifier.verifier_id,
        schema_version="genesis.m6a2d",
        verifier_version=DifferentialVerifier.verifier_version,
        verifier_kind=VerifierKind.DIFFERENTIAL,
        authority_class=AuthorityClass.DIFFERENTIAL,
        sovereignty=VerifierSovereignty.SUPPORTING,
        supported_claim_types=(ClaimType.EXACT_FUNCTION.value,),
        supported_obligation_kinds=("differential",),
        implementation_identity_hash=identity.identity_hash,
        dependency_manifest_hash=h("differential-no-external-dependencies"),
        cost_class="finite-exhaustive",
        deterministic=True,
    )


def test_implementation_identity_is_stable_and_descriptor_is_not_sovereign() -> None:
    first = DifferentialVerifier.implementation_identity()
    second = DifferentialVerifier.implementation_identity()
    differential_descriptor = descriptor()

    assert first == second
    assert first.module_relative_path == "lab/genesis/verifiers/differential.py"
    assert first.symbol_name == "DifferentialVerifier"
    assert differential_descriptor.implementation_identity_hash == first.identity_hash
    assert differential_descriptor.sovereignty is VerifierSovereignty.SUPPORTING


def times_two(value: int) -> int:
    return 2 * value


def constant_seven(_: int) -> int:
    return 7


def times_three(value: int) -> int:
    return 3 * value


def boundary_mutant(value: int) -> int:
    return 0 if value == 10 else 2 * value


def single_input_mutant(value: int) -> int:
    return 99 if value == 3 else 2 * value


def context(
    claim: TypedClaim,
    *,
    candidate_identity_hash: str,
    reference_identity_hash: str,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "claim": claim,
        "plan_hash": h("plan"),
        "snapshot_hash": h("snapshot"),
        "candidate_identity_hash": candidate_identity_hash,
        "reference_identity_hash": reference_identity_hash,
    }
    value["context_hash"] = canonical_execution_context_hash(
        claim.claim_hash, candidate_identity_hash, value
    )
    return value


def verifier(reference: Callable[[int], int], reference_name: str) -> DifferentialVerifier:
    return DifferentialVerifier(reference, reference_identity_hash=h(("reference", reference_name)))


def case(
    claim: TypedClaim,
    *,
    case_id: str,
    case_class: ReliabilityCaseClass,
    expected_verdict: ReceiptStatus,
    candidate_name: str,
    reference_name: str,
) -> ReliabilityCase:
    candidate_identity_hash = h(("candidate", candidate_name))
    reference_identity_hash = h(("reference", reference_name))
    case_context = context(
        claim,
        candidate_identity_hash=candidate_identity_hash,
        reference_identity_hash=reference_identity_hash,
    )
    return ReliabilityCase(
        case_id=case_id,
        schema_version="genesis.m6a2d",
        claim_hash=claim.claim_hash,
        case_class=case_class,
        expected_verdict=expected_verdict,
        candidate_identity_hash=candidate_identity_hash,
        reference_identity_hash=reference_identity_hash,
        domain_hash=canonical_sha256(claim.domain),
        context_hash=case_context["context_hash"],
        source_provenance_hash=h("external-differential-ground-truth-v1"),
    )


def execution(
    claim: TypedClaim,
    reliability_case: ReliabilityCase,
    candidate: Callable[[int], int],
    reference: Callable[[int], int],
    reference_name: str,
    *,
    verifier_override: Any | None = None,
) -> tuple[Any, Callable[[int], int], Mapping[str, Any]]:
    return (
        verifier_override or verifier(reference, reference_name),
        candidate,
        context(
            claim,
            candidate_identity_hash=reliability_case.candidate_identity_hash,
            reference_identity_hash=reliability_case.reference_identity_hash or "",
        ),
    )


def test_two_x_is_supported_by_differential_and_honestly_unknown_to_exact() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")
    execution_context = context(
        claim,
        candidate_identity_hash=h(("candidate", "times-two")),
        reference_identity_hash=subject.reference_identity_hash,
    )

    differential = subject.verify(claim, times_two, execution_context)
    exact = ExactVerifier().verify(claim, times_two, execution_context)

    assert differential.status is ReceiptStatus.PASS
    assert differential.coverage == {"evaluated_inputs": 21, "declared_inputs": 21}
    assert exact.status is ReceiptStatus.UNKNOWN
    assert exact.evidence["reason"] == "unsupported_exact_specification"


def test_constant_function_is_supported_by_differential() -> None:
    claim = differential_claim()
    subject = verifier(constant_seven, "constant-seven")

    receipt = subject.verify(
        claim,
        constant_seven,
        context(
            claim,
            candidate_identity_hash=h(("candidate", "constant-seven")),
            reference_identity_hash=subject.reference_identity_hash,
        ),
    )

    assert receipt.status is ReceiptStatus.PASS
    assert receipt.coverage["evaluated_inputs"] == receipt.coverage["declared_inputs"]


def test_wrong_multiplier_produces_reproducible_counterexamples() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")
    receipt = subject.verify(
        claim,
        times_three,
        context(
            claim,
            candidate_identity_hash=h(("candidate", "times-three")),
            reference_identity_hash=subject.reference_identity_hash,
        ),
    )

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.counterexamples[0] == {
        "input": -10,
        "candidate_output": -30,
        "reference_output": -20,
    }
    assert receipt.receipt_hash == canonical_sha256(receipt.canonical_payload())


def test_boundary_mutant_is_detected_at_the_declared_boundary() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")
    receipt = subject.verify(
        claim,
        boundary_mutant,
        context(
            claim,
            candidate_identity_hash=h(("candidate", "boundary-mutant")),
            reference_identity_hash=subject.reference_identity_hash,
        ),
    )

    assert receipt.status is ReceiptStatus.FAIL
    assert {item["input"] for item in receipt.counterexamples} == {10}
    assert receipt.counterexamples[0]["candidate_output"] == 0
    assert receipt.counterexamples[0]["reference_output"] == 20


def test_single_input_corruption_is_detected() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")
    receipt = subject.verify(
        claim,
        single_input_mutant,
        context(
            claim,
            candidate_identity_hash=h(("candidate", "single-input-mutant")),
            reference_identity_hash=subject.reference_identity_hash,
        ),
    )

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.counterexamples == (
        {"input": 3, "candidate_output": 99, "reference_output": 6},
    )


def test_candidate_receives_only_its_input_not_reference_material_or_context() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")
    visible_arguments: list[tuple[object, ...]] = []

    def instrumented_candidate(value: int, *extra: object) -> int:
        visible_arguments.append(extra)
        return 2 * value

    execution_context = context(
        claim,
        candidate_identity_hash=h(("candidate", "instrumented")),
        reference_identity_hash=subject.reference_identity_hash,
    )
    assert not {
        "reference",
        "reference_callable",
        "reference_outputs",
        "expected_outputs",
        "reference_payload",
    } & set(execution_context)

    receipt = subject.verify(claim, instrumented_candidate, execution_context)

    assert receipt.status is ReceiptStatus.PASS
    assert visible_arguments == [()] * 21


def test_reference_identity_is_sealed_and_reference_switch_changes_evidence() -> None:
    claim = differential_claim()
    first = verifier(times_two, "times-two-v1")
    second = verifier(times_two, "times-two-v2")
    candidate_identity_hash = h(("candidate", "times-two"))

    receipt_a = first.verify(
        claim,
        times_two,
        context(
            claim,
            candidate_identity_hash=candidate_identity_hash,
            reference_identity_hash=first.reference_identity_hash,
        ),
    )
    receipt_b = second.verify(
        claim,
        times_two,
        context(
            claim,
            candidate_identity_hash=candidate_identity_hash,
            reference_identity_hash=second.reference_identity_hash,
        ),
    )

    assert receipt_a.status is receipt_b.status is ReceiptStatus.PASS
    assert receipt_a.evidence["reference_identity_hash"] != receipt_b.evidence[
        "reference_identity_hash"
    ]
    assert receipt_a.receipt_hash != receipt_b.receipt_hash


def test_reference_identity_and_context_tampering_are_rejected() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")
    candidate_identity_hash = h(("candidate", "times-two"))
    valid_context = context(
        claim,
        candidate_identity_hash=candidate_identity_hash,
        reference_identity_hash=subject.reference_identity_hash,
    )
    wrong_reference = dict(valid_context)
    wrong_reference["reference_identity_hash"] = h(("reference", "substituted"))
    altered_context = dict(valid_context)
    altered_context["plan_hash"] = h("substituted-plan")

    reference_receipt = subject.verify(claim, times_two, wrong_reference)
    context_receipt = subject.verify(claim, times_two, altered_context)

    assert reference_receipt.status is ReceiptStatus.ERROR
    assert reference_receipt.evidence["reason"] == "reference_identity_hash_mismatch"
    assert context_receipt.status is ReceiptStatus.ERROR
    assert context_receipt.evidence["reason"] == "context_hash_invalid"


@pytest.mark.parametrize(
    ("claim", "candidate", "context_override", "expected_status"),
    (
        (
            differential_claim(),
            times_two,
            {},
            ReceiptStatus.PASS,
        ),
        (
            TypedClaim(
                claim_id="unsupported",
                schema_version="genesis.m6a2d",
                claim_type=ClaimType.EXACT_FUNCTION,
                properties={"relation": "not-differential"},
                assumptions=(),
                domain={"kind": "integer_range", "min": 0, "max": 1},
                budget={},
                falsifiers=(),
                obligations=(),
                risk_class="low",
                change_class=ChangeClass.NOT_APPLICABLE,
            ),
            times_two,
            {},
            ReceiptStatus.UNKNOWN,
        ),
    ),
)
def test_supported_and_unsupported_specifications_are_distinguished(
    claim: TypedClaim,
    candidate: Callable[[int], int],
    context_override: Mapping[str, Any],
    expected_status: ReceiptStatus,
) -> None:
    subject = verifier(times_two, "times-two")
    execution_context = context(
        claim,
        candidate_identity_hash=h(("candidate", "times-two")),
        reference_identity_hash=subject.reference_identity_hash,
    )
    execution_context.update(context_override)

    assert subject.verify(claim, candidate, execution_context).status is expected_status


def test_execution_error_is_not_reinterpreted_as_pass_or_fail() -> None:
    claim = differential_claim()
    subject = verifier(times_two, "times-two")

    def broken_candidate(_: int) -> int:
        raise RuntimeError("test-only")

    receipt = subject.verify(
        claim,
        broken_candidate,
        context(
            claim,
            candidate_identity_hash=h(("candidate", "broken")),
            reference_identity_hash=subject.reference_identity_hash,
        ),
    )

    assert receipt.status is ReceiptStatus.ERROR
    assert receipt.evidence["reason"] == "execution_error:RuntimeError"


class BlindDifferentialVerifier:
    """Controlled defective double used to prove M6A-1 derives degradation."""

    verifier_id = DifferentialVerifier.verifier_id
    verifier_version = DifferentialVerifier.verifier_version

    def __init__(self, reference: Callable[[int], int], reference_identity_hash: str) -> None:
        self._actual = DifferentialVerifier(
            reference, reference_identity_hash=reference_identity_hash
        )

    def verify(
        self, claim: TypedClaim, candidate: Any, execution_context: Mapping[str, Any]
    ) -> VerifierReceipt:
        actual = self._actual.verify(claim, candidate, execution_context)
        return replace(
            actual,
            status=ReceiptStatus.PASS,
            evidence={"reason": "blind-differential-test-double"},
            counterexamples=(),
        )


def test_real_differential_campaign_is_characterized_and_replay_consistent() -> None:
    claim = differential_claim()
    cases = (
        case(
            claim,
            case_id="two-x-truth",
            case_class=ReliabilityCaseClass.TRUE_CASE,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="times-two",
            reference_name="times-two",
        ),
        case(
            claim,
            case_id="constant-truth",
            case_class=ReliabilityCaseClass.TRUE_CASE,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="constant-seven",
            reference_name="constant-seven",
        ),
        case(
            claim,
            case_id="wrong-multiplier-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="times-three",
            reference_name="times-two",
        ),
        case(
            claim,
            case_id="boundary-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="boundary-mutant",
            reference_name="times-two",
        ),
        case(
            claim,
            case_id="single-input-mutant",
            case_class=ReliabilityCaseClass.MUTANT,
            expected_verdict=ReceiptStatus.FAIL,
            candidate_name="single-input-mutant",
            reference_name="times-two",
        ),
        case(
            claim,
            case_id="two-x-replay",
            case_class=ReliabilityCaseClass.REPLAY,
            expected_verdict=ReceiptStatus.PASS,
            candidate_name="times-two-replay",
            reference_name="times-two",
        ),
    )
    executions = {
        cases[0].case_hash: execution(claim, cases[0], times_two, times_two, "times-two"),
        cases[1].case_hash: execution(
            claim, cases[1], constant_seven, constant_seven, "constant-seven"
        ),
        cases[2].case_hash: execution(claim, cases[2], times_three, times_two, "times-two"),
        cases[3].case_hash: execution(
            claim, cases[3], boundary_mutant, times_two, "times-two"
        ),
        cases[4].case_hash: execution(
            claim, cases[4], single_input_mutant, times_two, "times-two"
        ),
        cases[5].case_hash: execution(claim, cases[5], times_two, times_two, "times-two"),
    }
    differential_descriptor = descriptor()

    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6a2d-real-campaign",
        descriptor=differential_descriptor,
        implementation_identity_hash=differential_descriptor.implementation_identity_hash,
        cases=cases,
        executions=executions,
        campaign_policy_hash=h("m6a2d-reliability-policy"),
    )

    assert receipt.validate()
    assert receipt.correct_cases == 2
    assert receipt.mutation_cases == 3
    assert receipt.mutations_detected == 3
    assert receipt.replay_cases == receipt.replay_consistent == 1
    assert profile.status is ReliabilityStatus.CHARACTERIZED
    assert validate_profile_binding(
        profile,
        receipt,
        differential_descriptor.descriptor_hash,
        differential_descriptor.implementation_identity_hash,
    )
    assert not validate_profile_binding(
        profile,
        receipt,
        differential_descriptor.descriptor_hash,
        h("wrong-implementation-identity"),
    )


def test_blind_differential_campaign_is_degraded_from_observed_mutation_miss() -> None:
    claim = differential_claim()
    truth = case(
        claim,
        case_id="blind-truth",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="times-two",
        reference_name="times-two",
    )
    mutant = case(
        claim,
        case_id="blind-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="times-three",
        reference_name="times-two",
    )
    blind = BlindDifferentialVerifier(times_two, mutant.reference_identity_hash or "")
    differential_descriptor = descriptor()

    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id="m6a2d-blind-campaign",
        descriptor=differential_descriptor,
        implementation_identity_hash=differential_descriptor.implementation_identity_hash,
        cases=(truth, mutant),
        executions={
            truth.case_hash: execution(
                claim,
                truth,
                times_two,
                times_two,
                "times-two",
                verifier_override=blind,
            ),
            mutant.case_hash: execution(
                claim,
                mutant,
                times_three,
                times_two,
                "times-two",
                verifier_override=blind,
            ),
        },
        campaign_policy_hash=h("m6a2d-reliability-policy"),
    )

    assert receipt.mutation_cases == 1
    assert receipt.mutations_detected == 0
    assert profile.status is ReliabilityStatus.DEGRADED
    assert "required_mutation_missed" in profile.reason_codes
