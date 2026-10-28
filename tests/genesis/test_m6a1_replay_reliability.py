"""Replay-consistency falsification tests for M6A-1 campaigns."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

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
    x_plus_two,
)


class FlakyDeclaredDeterministicVerifier:
    """A controlled, deterministic-in-the-test but scientifically flaky verifier.

    It changes the second result for each identical execution pair.  This is
    intentionally not randomness: a failed replay must be reproducibly
    detectable by a campaign that is told the descriptor is deterministic.
    """

    verifier_id = "m6a1.flaky"
    verifier_version = "v1"

    def __init__(self) -> None:
        self._exact = ExactVerifier()
        self.calls = 0

    def verify(self, claim: Any, candidate: Any, context: Mapping[str, Any]):
        self.calls += 1
        stable = replace(
            self._exact.verify(claim, candidate, context),
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
        )
        if self.calls % 2:
            return stable
        opposite = (
            ReceiptStatus.FAIL
            if stable.status is ReceiptStatus.PASS
            else ReceiptStatus.PASS
        )
        return replace(
            stable,
            status=opposite,
            evidence={"reason": "controlled-replay-divergence", "call": self.calls},
            counterexamples=(),
        )


def test_exact_verifier_replay_is_scientifically_consistent() -> None:
    claim = exact_claim()
    truth = make_case(
        claim,
        case_id="replay-truth",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    mutant = make_case(
        claim,
        case_id="replay-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="x-plus-two",
    )
    replay = make_case(
        claim,
        case_id="replay-exact-plus-one",
        case_class=ReliabilityCaseClass.REPLAY,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one-replay",
    )
    exact = ExactVerifier()

    receipt, profile = run_campaign(
        (truth, mutant, replay),
        {
            truth.case_hash: (exact, plus_one, execution_context(claim, truth)),
            mutant.case_hash: (exact, x_plus_two, execution_context(claim, mutant)),
            replay.case_hash: (exact, plus_one, execution_context(claim, replay)),
        },
    )

    assert receipt.replay_cases == 1
    assert receipt.replay_consistent == 1
    replay_result = next(
        result for result in receipt.case_results if result.case_hash == replay.case_hash
    )
    assert replay_result.replay_consistent is True
    assert replay_result.replay_semantic_result_hash == replay_result.semantic_result_hash
    assert profile.status is ReliabilityStatus.CHARACTERIZED


def test_declared_deterministic_verifier_with_divergent_replay_is_degraded() -> None:
    claim = exact_claim()
    truth = make_case(
        claim,
        case_id="flaky-replay-truth",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    mutant = make_case(
        claim,
        case_id="flaky-replay-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="x-plus-two",
    )
    replay = make_case(
        claim,
        case_id="flaky-required-replay",
        case_class=ReliabilityCaseClass.REPLAY,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one-replay",
    )
    flaky = FlakyDeclaredDeterministicVerifier()
    flaky_descriptor = exact_descriptor(
        verifier_id=flaky.verifier_id,
        verifier_version=flaky.verifier_version,
        implementation_identity_hash="flaky-test-implementation",
    )

    receipt, profile = run_campaign(
        (truth, mutant, replay),
        {
            truth.case_hash: (flaky, plus_one, execution_context(claim, truth)),
            mutant.case_hash: (flaky, x_plus_two, execution_context(claim, mutant)),
            replay.case_hash: (flaky, plus_one, execution_context(claim, replay)),
        },
        descriptor=flaky_descriptor,
    )

    assert flaky.calls == 4
    assert receipt.replay_cases == 1
    assert receipt.replay_consistent < receipt.replay_cases
    replay_result = next(
        result for result in receipt.case_results if result.case_hash == replay.case_hash
    )
    assert replay_result.replay_consistent is False
    assert replay_result.replay_semantic_result_hash != replay_result.semantic_result_hash
    assert profile.status is ReliabilityStatus.DEGRADED
    assert any("replay" in code.lower() for code in profile.reason_codes)


def test_insufficient_but_non_adverse_campaign_is_uncharacterized() -> None:
    claim = exact_claim()
    truth = make_case(
        claim,
        case_id="only-truth-no-required-mutant",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )

    receipt, profile = run_campaign(
        (truth,),
        {truth.case_hash: (ExactVerifier(), plus_one, execution_context(claim, truth))},
    )

    assert receipt.truth_known_cases == 1
    assert receipt.mutation_cases == 0
    assert receipt.error_cases == 0
    assert profile.status is ReliabilityStatus.UNCHARACTERIZED
    assert "campaign_required_check_failed" not in profile.reason_codes
    assert any("incomplete" in code.lower() for code in profile.reason_codes)


def test_missing_explicit_replay_is_uncharacterized_under_m6a1_policy() -> None:
    claim = exact_claim()
    truth = make_case(
        claim,
        case_id="no-replay-truth",
        case_class=ReliabilityCaseClass.TRUE_CASE,
        expected_verdict=ReceiptStatus.PASS,
        candidate_name="plus-one",
    )
    mutant = make_case(
        claim,
        case_id="no-replay-mutant",
        case_class=ReliabilityCaseClass.MUTANT,
        expected_verdict=ReceiptStatus.FAIL,
        candidate_name="x-plus-two",
    )

    receipt, profile = run_campaign(
        (truth, mutant),
        {
            truth.case_hash: (ExactVerifier(), plus_one, execution_context(claim, truth)),
            mutant.case_hash: (ExactVerifier(), x_plus_two, execution_context(claim, mutant)),
        },
    )

    assert receipt.truth_known_cases == 1
    assert receipt.mutation_cases == 1
    assert receipt.mutations_detected == 1
    assert receipt.replay_cases == 0
    assert profile.status is ReliabilityStatus.UNCHARACTERIZED
    assert "campaign_policy_incomplete" in profile.reason_codes
