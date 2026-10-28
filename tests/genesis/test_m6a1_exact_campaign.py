"""Real ExactVerifier campaigns used to falsify M6A-1 reliability counts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

import pytest

from lab.genesis.contracts.receipts import ReceiptStatus
from lab.genesis.verifiers.exact import ExactVerifier
from lab.genesis.verifiers.reliability import ReliabilityStatus
from lab.genesis.verifiers.reliability_campaign import ReliabilityCaseClass
from tests.genesis.test_m6a1_reliability_case import (
    exact_claim,
    exact_descriptor,
    execution_context,
    make_case,
    plus_one,
    run_campaign,
)


def x_plus_two(value: int) -> int:
    return value + 2


def boundary_corruption(value: int) -> int:
    return value if value == 10 else value + 1


def wrong_sign(value: int) -> int:
    return 1 - value


def single_input_corruption(value: int) -> int:
    return value if value == 3 else value + 1


class RecordingExactVerifier:
    """A transparent call recorder: scientific checking remains ExactVerifier."""

    verifier_id = ExactVerifier.verifier_id
    verifier_version = ExactVerifier.verifier_version

    def __init__(self) -> None:
        self._exact = ExactVerifier()
        self.receipts = []

    def verify(self, claim: Any, candidate: Any, context: Mapping[str, Any]):
        receipt = self._exact.verify(claim, candidate, context)
        self.receipts.append(receipt)
        return receipt


class BlindPassVerifier:
    """Deliberately defective test double used only to prove derived counters."""

    verifier_id = "m6a1.blind-pass"
    verifier_version = "v1"

    def __init__(self) -> None:
        self._exact = ExactVerifier()
        self.calls = 0

    def verify(self, claim: Any, candidate: Any, context: Mapping[str, Any]):
        self.calls += 1
        exact_receipt = self._exact.verify(claim, candidate, context)
        return replace(
            exact_receipt,
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
            status=ReceiptStatus.PASS,
            evidence={"reason": "blind-pass-test-double"},
            counterexamples=(),
        )


@pytest.mark.parametrize(
    ("name", "candidate", "counterexample_matches"),
    (
        ("x_plus_2", x_plus_two, lambda counterexample: True),
        (
            "boundary",
            boundary_corruption,
            lambda counterexample: counterexample["input"] == 10,
        ),
        ("wrong_sign", wrong_sign, lambda counterexample: True),
        (
            "single_input",
            single_input_corruption,
            lambda counterexample: counterexample["input"] == 3,
        ),
    ),
)
def test_exact_verifier_detects_each_real_mutant(
    name: str,
    candidate: Callable[[int], int],
    counterexample_matches: Callable[[Mapping[str, int]], bool],
) -> None:
    claim = exact_claim()

    observed = ExactVerifier().verify(claim, candidate, execution_context(claim))

    assert observed.status is ReceiptStatus.FAIL, name
    assert observed.counterexamples, name
    assert any(counterexample_matches(item) for item in observed.counterexamples), name


def test_exact_campaign_derives_truth_and_mutation_counts_from_real_receipts() -> None:
    claim = exact_claim()
    cases_and_candidates = (
        (
            make_case(
                claim,
                case_id="truth-plus-one",
                case_class=ReliabilityCaseClass.TRUE_CASE,
                expected_verdict=ReceiptStatus.PASS,
                candidate_name="plus-one",
            ),
            plus_one,
        ),
        (
            make_case(
                claim,
                case_id="mutant-x-plus-two",
                case_class=ReliabilityCaseClass.MUTANT,
                expected_verdict=ReceiptStatus.FAIL,
                candidate_name="x-plus-two",
            ),
            x_plus_two,
        ),
        (
            make_case(
                claim,
                case_id="mutant-boundary-at-ten",
                case_class=ReliabilityCaseClass.MUTANT,
                expected_verdict=ReceiptStatus.FAIL,
                candidate_name="boundary-corruption",
            ),
            boundary_corruption,
        ),
        (
            make_case(
                claim,
                case_id="mutant-wrong-sign",
                case_class=ReliabilityCaseClass.MUTANT,
                expected_verdict=ReceiptStatus.FAIL,
                candidate_name="wrong-sign",
            ),
            wrong_sign,
        ),
        (
            make_case(
                claim,
                case_id="mutant-single-input",
                case_class=ReliabilityCaseClass.MUTANT,
                expected_verdict=ReceiptStatus.FAIL,
                candidate_name="single-input-corruption",
            ),
            single_input_corruption,
        ),
        (
            make_case(
                claim,
                case_id="replay-plus-one",
                case_class=ReliabilityCaseClass.REPLAY,
                expected_verdict=ReceiptStatus.PASS,
                candidate_name="plus-one-replay",
            ),
            plus_one,
        ),
    )
    exact = RecordingExactVerifier()
    cases = tuple(case for case, _ in cases_and_candidates)
    executions = {
        case.case_hash: (exact, candidate, execution_context(claim, case))
        for case, candidate in cases_and_candidates
    }

    receipt, profile = run_campaign(cases, executions)

    # Only the explicitly declared replay case is run a second time.
    assert len(exact.receipts) == len(cases) + receipt.replay_cases
    assert receipt.truth_known_cases == 1
    assert receipt.correct_cases == 1
    assert receipt.incorrect_cases == 0
    assert receipt.error_cases == 0
    assert receipt.mutation_cases == 4
    assert receipt.mutations_detected == 4
    assert receipt.replay_cases == 1
    assert receipt.replay_consistent == 1
    mutant_hashes = {
        case.case_hash
        for case in cases
        if case.case_class is ReliabilityCaseClass.MUTANT
    }
    assert all(
        result.observed_verdict is ReceiptStatus.FAIL
        for result in receipt.case_results
        if result.case_hash in mutant_hashes
    )
    replay_result = next(
        result
        for result in receipt.case_results
        if result.case_hash
        == next(
            case.case_hash
            for case in cases
            if case.case_class is ReliabilityCaseClass.REPLAY
        )
    )
    assert replay_result.replay_consistent is True
    assert replay_result.replay_semantic_result_hash == replay_result.semantic_result_hash
    assert profile.status is ReliabilityStatus.CHARACTERIZED
    assert profile.campaign_receipt_hash == receipt.campaign_hash


def test_mutation_miss_is_observed_and_degrades_the_profile() -> None:
    claim = exact_claim()
    truth = make_case(
        claim,
        case_id="truth-for-blind-verifier",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    mutant = make_case(
        claim,
        case_id="missed-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="x-plus-two",
    )
    blind = BlindPassVerifier()
    blind_descriptor = exact_descriptor(
        verifier_id=blind.verifier_id,
        verifier_version=blind.verifier_version,
        implementation_identity_hash="blind-pass-test-implementation",
    )

    receipt, profile = run_campaign(
        (truth, mutant),
        {
            truth.case_hash: (blind, plus_one, execution_context(claim, truth)),
            mutant.case_hash: (blind, x_plus_two, execution_context(claim, mutant)),
        },
        descriptor=blind_descriptor,
    )

    assert blind.calls == 2
    assert receipt.mutation_cases == 1
    assert receipt.mutations_detected == 0
    assert any(
        result.observed_verdict is ReceiptStatus.PASS
        for result in receipt.case_results
        if result.case_hash == mutant.case_hash
    )
    assert profile.status is ReliabilityStatus.DEGRADED
    assert any("mutation" in code.lower() for code in profile.reason_codes)
