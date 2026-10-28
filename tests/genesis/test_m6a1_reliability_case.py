"""Focused falsification tests for M6A-1 reliability cases.

These helpers deliberately use the real ``ExactVerifier`` contract.  A
ReliabilityCase is constructed before a verifier is even instantiated, so the
tests make the ground-truth boundary observable rather than merely asserting
that a field happens to exist.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, Callable, Mapping

import pytest

from lab.genesis.contracts.claims import ChangeClass, ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers.descriptor import (
    AuthorityClass,
    VerifierDescriptor,
    VerifierKind,
    VerifierSovereignty,
)
from lab.genesis.verifiers.exact import ExactVerifier
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCase,
    ReliabilityCaseClass,
    VerifierReliabilityCampaign,
)


def h(value: object) -> str:
    """A stable test-only identity, never an assertion shortcut."""

    return canonical_sha256({"m6a1_test": value})


def exact_claim(*, lower: int = -10, upper: int = 10) -> TypedClaim:
    return TypedClaim(
        claim_id="m6a1-exact-plus-one",
        schema_version="genesis.m6a1",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={"relation": "output_eq_input_plus", "delta": 1},
        assumptions=(),
        domain={"kind": "integer_range", "min": lower, "max": upper},
        budget={},
        falsifiers=("counterexample",),
        obligations=("exact",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )


def exact_descriptor(
    *, implementation_identity_hash: str | None = None,
    deterministic: bool = True,
    verifier_id: str = ExactVerifier.verifier_id,
    verifier_version: str = ExactVerifier.verifier_version,
) -> VerifierDescriptor:
    implementation_identity_hash = implementation_identity_hash or h("exact-impl-v1")
    return VerifierDescriptor(
        verifier_id=verifier_id,
        schema_version="genesis.m6a1",
        verifier_version=verifier_version,
        verifier_kind=VerifierKind.EXACT_EXECUTABLE,
        authority_class=AuthorityClass.EXACT,
        sovereignty=VerifierSovereignty.SOVEREIGN,
        supported_claim_types=(ClaimType.EXACT_FUNCTION.value,),
        supported_obligation_kinds=("exact",),
        implementation_identity_hash=implementation_identity_hash,
        dependency_manifest_hash=h("exact-dependencies"),
        cost_class="test",
        deterministic=deterministic,
    )


def execution_context(
    claim: TypedClaim, case: ReliabilityCase | None = None
) -> dict[str, Any]:
    context = {
        "claim": claim,
        "plan_hash": h("plan"),
        "snapshot_hash": h("snapshot"),
    }
    if case is not None:
        context["candidate_identity_hash"] = case.candidate_identity_hash
        context["context_hash"] = case.context_hash
    return context


def make_case(
    claim: TypedClaim,
    *,
    case_id: str,
    case_class: ReliabilityCaseClass,
    expected_verdict: ReceiptStatus,
    candidate_name: str,
    source_provenance_hash: str | None = None,
) -> ReliabilityCase:
    candidate_identity_hash = h(("candidate", candidate_name))
    context_hash = canonical_sha256(
        {
            "claim_hash": claim.claim_hash,
            "candidate_identity_hash": candidate_identity_hash,
            "plan_hash": h("plan"),
            "snapshot_hash": h("snapshot"),
        }
    )
    return ReliabilityCase(
        case_id=case_id,
        schema_version="genesis.m6a1",
        claim_hash=claim.claim_hash,
        case_class=case_class,
        expected_verdict=expected_verdict,
        candidate_identity_hash=candidate_identity_hash,
        reference_identity_hash=h("external-exact-spec"),
        domain_hash=canonical_sha256(claim.domain),
        context_hash=context_hash,
        source_provenance_hash=source_provenance_hash or h("external-ground-truth"),
    )


def execution(
    case: ReliabilityCase,
    claim: TypedClaim,
    candidate: Callable[[int], int],
    verifier: Any | None = None,
) -> dict[str, tuple[Any, Callable[[int], int], Mapping[str, Any]]]:
    return {
        case.case_hash: (
            verifier if verifier is not None else ExactVerifier(),
            candidate,
            execution_context(claim, case),
        )
    }


def run_campaign(
    cases: tuple[ReliabilityCase, ...],
    executions: Mapping[str, tuple[Any, Any, Mapping[str, Any]]],
    *,
    descriptor: VerifierDescriptor | None = None,
    implementation_identity_hash: str | None = None,
    receipt_id: str = "m6a1-campaign",
):
    descriptor = descriptor or exact_descriptor()
    return VerifierReliabilityCampaign().run(
        receipt_id=receipt_id,
        descriptor=descriptor,
        implementation_identity_hash=(
            implementation_identity_hash or descriptor.implementation_identity_hash
        ),
        cases=cases,
        executions=executions,
        campaign_policy_hash=h("m6a1-required-replay-policy"),
    )


def plus_one(value: int) -> int:
    return value + 1


def x_plus_two(value: int) -> int:
    return value + 2


def minimally_complete_exact_campaign():
    """A genuine truth-known + mutant campaign, useful for tamper tests."""

    claim = exact_claim()
    truth = make_case(
        claim,
        case_id="truth-plus-one",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    mutant = make_case(
        claim,
        case_id="mutant-x-plus-two",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="x-plus-two",
    )
    replay = make_case(
        claim,
        case_id="replay-plus-one",
        case_class=ReliabilityCaseClass.REPLAY,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one-replay",
    )
    descriptor = exact_descriptor()
    receipt, profile = run_campaign(
        (truth, mutant, replay),
        {
            **execution(truth, claim, plus_one),
            **execution(mutant, claim, x_plus_two),
            **execution(replay, claim, plus_one),
        },
        descriptor=descriptor,
    )
    return claim, descriptor, (truth, mutant, replay), receipt, profile


def test_ground_truth_is_presealed_before_real_verifier_execution() -> None:
    claim = exact_claim()

    # This is the independent specification decision.  No verifier exists yet.
    case = make_case(
        claim,
        case_id="presealed-true-case",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
        source_provenance_hash=h("external-specification-v1"),
    )
    pre_execution_case_hash = case.case_hash

    verifier = ExactVerifier()
    observed = verifier.verify(claim, plus_one, execution_context(claim, case))
    receipt, _ = run_campaign((case,), execution(case, claim, plus_one, verifier))

    assert pre_execution_case_hash == case.case_hash
    assert observed.status is ReceiptStatus.PASS
    assert receipt.case_results[0].expected_verdict is ReceiptStatus.PASS
    assert receipt.case_results[0].observed_verdict is observed.status
    assert case.expected_verdict is ReceiptStatus.PASS
    with pytest.raises(FrozenInstanceError):
        case.expected_verdict = ReceiptStatus.FAIL  # type: ignore[misc]


def test_source_provenance_is_committed_and_tampering_is_rejected() -> None:
    claim = exact_claim()
    case = make_case(
        claim,
        case_id="source-bound-case",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
        source_provenance_hash=h("independent-reference-source"),
    )
    original_hash = case.case_hash
    assert original_hash == canonical_sha256(case.canonical_payload())

    # This models an illicit rewrite that retains the old published identity.
    object.__setattr__(case, "source_provenance_hash", h("forged-reference-source"))
    assert case.case_hash == original_hash
    assert case.case_hash != canonical_sha256(case.canonical_payload())
    assert not case.validate()
    with pytest.raises(ValueError, match="reliability_case_hash_invalid"):
        run_campaign((case,), execution(case, claim, plus_one))


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("expected_verdict", ReceiptStatus.FAIL),
        ("claim_hash", h("forged-claim")),
        ("candidate_identity_hash", h("forged-candidate")),
        ("domain_hash", h("forged-domain")),
        ("source_provenance_hash", h("forged-source")),
    ),
)
def test_case_tampering_is_rejected_before_verifier_execution(
    field: str, forged_value: object
) -> None:
    claim = exact_claim()
    case = make_case(
        claim,
        case_id=f"tamper-{field}",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    original_hash = case.case_hash
    object.__setattr__(case, field, forged_value)

    assert case.case_hash == original_hash
    assert case.case_hash != canonical_sha256(case.canonical_payload())
    assert not case.validate()
    with pytest.raises(ValueError, match="reliability_case_hash_invalid"):
        run_campaign((case,), execution(case, claim, plus_one))


def test_execution_claim_cannot_be_substituted_for_the_presealed_case_claim() -> None:
    claim_a = exact_claim()
    claim_b = exact_claim(lower=-9, upper=10)
    case = make_case(
        claim_a,
        case_id="claim-a-execution-b",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )

    with pytest.raises(ValueError):
        run_campaign(
            (case,),
            {
                case.case_hash: (
                    ExactVerifier(),
                    plus_one,
                    execution_context(claim_b, case),
                )
            },
        )


def test_execution_candidate_identity_cannot_differ_from_presealed_case() -> None:
    claim = exact_claim()
    case = make_case(
        claim,
        case_id="candidate-a-execution-b",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    context = execution_context(claim, case)
    context["candidate_identity_hash"] = h("substituted-candidate-identity")

    with pytest.raises(ValueError):
        run_campaign(
            (case,),
            {case.case_hash: (ExactVerifier(), x_plus_two, context)},
        )


def test_execution_context_contents_cannot_change_after_case_preseal() -> None:
    claim = exact_claim()
    case = make_case(
        claim,
        case_id="context-a-execution-b",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    context = execution_context(claim, case)
    # The advertised context hash remains old; recomputation must notice this.
    context["plan_hash"] = h("substituted-plan")

    with pytest.raises(ValueError):
        run_campaign(
            (case,),
            {case.case_hash: (ExactVerifier(), plus_one, context)},
        )
