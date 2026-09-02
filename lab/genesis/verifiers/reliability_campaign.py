"""Predeclared-ground-truth reliability characterization for verifiers.

M6A-1 characterizes a verifier only inside a sealed campaign.  In
particular, a verifier never supplies the expected verdict that is used to
judge it, and a reliability profile is rebuilt from the receipt rather than
trusted as an independently authored label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.verifiers.bindings import canonical_execution_context_hash
from lab.genesis.verifiers.descriptor import VerifierDescriptor
from lab.genesis.verifiers.reliability import (
    ReliabilityStatus,
    VerifierReliabilityProfile,
)


class ReliabilityCaseClass(str, Enum):
    TRUE_CASE = "TRUE_CASE"
    FALSE_CASE = "FALSE_CASE"
    MUTANT = "MUTANT"
    REPLAY = "REPLAY"
    ADVERSARIAL = "ADVERSARIAL"


@dataclass(frozen=True, slots=True)
class ReliabilityCase:
    """An externally decided verdict and the inputs it is allowed to judge."""

    case_id: str
    schema_version: str
    claim_hash: str
    case_class: ReliabilityCaseClass
    expected_verdict: ReceiptStatus
    candidate_identity_hash: str
    reference_identity_hash: str | None
    domain_hash: str
    context_hash: str
    source_provenance_hash: str
    case_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_class", ReliabilityCaseClass(self.case_class))
        object.__setattr__(self, "expected_verdict", ReceiptStatus(self.expected_verdict))
        object.__setattr__(self, "case_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "claim_hash": self.claim_hash,
            "case_class": self.case_class.value,
            "expected_verdict": self.expected_verdict.value,
            "candidate_identity_hash": self.candidate_identity_hash,
            "reference_identity_hash": self.reference_identity_hash,
            "domain_hash": self.domain_hash,
            "context_hash": self.context_hash,
            "source_provenance_hash": self.source_provenance_hash,
        }

    def validate(self) -> bool:
        return self.case_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class ReliabilityExecution:
    """A sealed binding supplied by the execution orchestrator.

    Generic Python callables have no sound universal content hash.  The
    candidate loader therefore supplies its identity hash explicitly, and this
    object seals that identity together with the concrete claim and context
    used for execution.  The campaign rejects any mismatch with the presealed
    ``ReliabilityCase`` before it invokes the verifier.
    """

    verifier: Any
    candidate: Any
    claim: TypedClaim
    candidate_identity_hash: str
    context: Mapping[str, Any]
    context_hash: str
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", freeze(self.context))
        context_claim = self.context.get("claim")
        if (
            not isinstance(context_claim, TypedClaim)
            or context_claim.claim_hash != self.claim.claim_hash
        ):
            # Equal sealed claim content is permitted; a caller cannot hide a
            # different claim behind unrelated context metadata.
            raise ValueError("genesis_reliability_execution_claim_context_mismatch")
        if self.context.get("candidate_identity_hash") != self.candidate_identity_hash:
            raise ValueError("genesis_reliability_execution_candidate_context_mismatch")
        advertised_context_hash = self.context.get("context_hash")
        if advertised_context_hash != self.context_hash:
            raise ValueError("genesis_reliability_execution_context_metadata_mismatch")
        actual_context_hash = canonical_execution_context_hash(
            self.claim.claim_hash,
            self.candidate_identity_hash,
            self.context,
        )
        if actual_context_hash != self.context_hash:
            raise ValueError("genesis_reliability_execution_context_hash_invalid")
        object.__setattr__(
            self,
            "binding_hash",
            canonical_sha256(
                {
                    "claim_hash": self.claim.claim_hash,
                    "candidate_identity_hash": self.candidate_identity_hash,
                    "domain_hash": canonical_sha256(self.claim.domain),
                    "context_hash": self.context_hash,
                }
            ),
        )

    @classmethod
    def from_legacy_tuple(cls, value: tuple[Any, Any, Mapping[str, Any]]) -> "ReliabilityExecution":
        """Adapt the compact M6A-1 execution mapping without a parallel API."""

        try:
            verifier, candidate, context = value
        except (TypeError, ValueError) as exc:
            raise ValueError("genesis_reliability_execution_shape_invalid") from exc
        if not isinstance(context, Mapping):
            raise ValueError("genesis_reliability_execution_context_invalid")
        claim = context.get("claim")
        if not isinstance(claim, TypedClaim):
            raise ValueError("genesis_reliability_execution_claim_missing")
        candidate_identity_hash = context.get("candidate_identity_hash")
        context_hash = context.get("context_hash")
        if not isinstance(candidate_identity_hash, str):
            raise ValueError("genesis_reliability_execution_candidate_identity_missing")
        if not isinstance(context_hash, str):
            raise ValueError("genesis_reliability_execution_context_hash_missing")
        return cls(
            verifier=verifier,
            candidate=candidate,
            claim=claim,
            candidate_identity_hash=candidate_identity_hash,
            context=context,
            context_hash=context_hash,
        )


@dataclass(frozen=True, slots=True)
class ReliabilityCaseResult:
    """The sealed scientific observation for one presealed case."""

    case_hash: str
    expected_verdict: ReceiptStatus
    observed_verdict: ReceiptStatus
    verifier_receipt_hash: str
    semantic_result_hash: str
    correct: bool
    reason_codes: tuple[str, ...]
    replay_semantic_result_hash: str | None = None
    replay_consistent: bool | None = None
    replay_verifier_receipt_hash: str | None = None
    case_class: ReliabilityCaseClass = ReliabilityCaseClass.TRUE_CASE
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_verdict", ReceiptStatus(self.expected_verdict))
        object.__setattr__(self, "observed_verdict", ReceiptStatus(self.observed_verdict))
        object.__setattr__(self, "case_class", ReliabilityCaseClass(self.case_class))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "result_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "case_hash": self.case_hash,
            "expected_verdict": self.expected_verdict.value,
            "observed_verdict": self.observed_verdict.value,
            "verifier_receipt_hash": self.verifier_receipt_hash,
            "semantic_result_hash": self.semantic_result_hash,
            "correct": self.correct,
            "reason_codes": self.reason_codes,
            "replay_semantic_result_hash": self.replay_semantic_result_hash,
            "replay_consistent": self.replay_consistent,
            "replay_verifier_receipt_hash": self.replay_verifier_receipt_hash,
            "case_class": self.case_class.value,
        }

    def validate(self) -> bool:
        if self.result_hash != canonical_sha256(self.canonical_payload()):
            return False
        if self.correct is not (self.expected_verdict is self.observed_verdict):
            return False
        if self.case_class is ReliabilityCaseClass.REPLAY:
            return (
                isinstance(self.replay_semantic_result_hash, str)
                and isinstance(self.replay_verifier_receipt_hash, str)
                and isinstance(self.replay_consistent, bool)
                and self.replay_consistent
                == (self.semantic_result_hash == self.replay_semantic_result_hash)
            )
        return (
            self.replay_semantic_result_hash is None
            and self.replay_verifier_receipt_hash is None
            and self.replay_consistent is None
        )


def _count_receipt_results(
    results: Sequence[ReliabilityCaseResult],
) -> dict[str, int]:
    truth_results = tuple(
        result
        for result in results
        if result.case_class
        in {ReliabilityCaseClass.TRUE_CASE, ReliabilityCaseClass.FALSE_CASE}
    )
    mutant_results = tuple(
        result
        for result in results
        if result.case_class is ReliabilityCaseClass.MUTANT
    )
    replay_results = tuple(
        result
        for result in results
        if result.case_class is ReliabilityCaseClass.REPLAY
    )
    adversarial_results = tuple(
        result
        for result in results
        if result.case_class is ReliabilityCaseClass.ADVERSARIAL
    )
    return {
        "truth_known_cases": len(truth_results),
        "correct_cases": sum(result.correct for result in truth_results),
        "incorrect_cases": sum(not result.correct for result in truth_results),
        "unknown_cases": sum(
            result.observed_verdict is ReceiptStatus.UNKNOWN for result in results
        ),
        "error_cases": sum(
            result.observed_verdict is ReceiptStatus.ERROR for result in results
        ),
        "mutation_cases": len(mutant_results),
        "mutations_detected": sum(
            result.correct and result.expected_verdict is ReceiptStatus.FAIL
            for result in mutant_results
        ),
        "replay_cases": len(replay_results),
        "replay_consistent": sum(
            bool(result.replay_consistent) for result in replay_results
        ),
        "adversarial_cases": len(adversarial_results),
        "adversarial_detected": sum(
            result.correct and result.expected_verdict is ReceiptStatus.FAIL
            for result in adversarial_results
        ),
    }


def _campaign_complete(counts: Mapping[str, int]) -> bool:
    """M6A-1's minimum sealed characterization policy.

    The opaque policy hash commits the external policy artifact.  This first
    executable campaign has one fixed minimum so its receipt remains
    self-validating: at least one truth-known result, one mutation probe, and
    one explicitly repeated execution. Later milestones may introduce richer
    policy descriptors without weakening this evidence.
    """

    return (
        counts["truth_known_cases"] >= 1
        and counts["mutation_cases"] >= 1
        and counts["replay_cases"] >= 1
    )


def _campaign_reason_codes(
    results: Sequence[ReliabilityCaseResult], counts: Mapping[str, int]
) -> tuple[str, ...]:
    truth_results = tuple(
        result
        for result in results
        if result.case_class
        in {ReliabilityCaseClass.TRUE_CASE, ReliabilityCaseClass.FALSE_CASE}
    )
    mutant_results = tuple(
        result
        for result in results
        if result.case_class is ReliabilityCaseClass.MUTANT
    )
    replay_results = tuple(
        result
        for result in results
        if result.case_class is ReliabilityCaseClass.REPLAY
    )
    reasons: list[str] = []
    if counts["error_cases"]:
        reasons.append("required_execution_error")
    if any(not result.correct for result in truth_results):
        reasons.append("required_truth_known_failed")
    if any(
        not result.correct and result.expected_verdict is ReceiptStatus.FAIL
        for result in mutant_results
    ):
        reasons.append("required_mutation_missed")
    if any(not result.correct for result in replay_results):
        reasons.append("required_replay_verdict_failed")
    if any(not result.replay_consistent for result in replay_results):
        reasons.append("required_replay_inconsistent")
    if not _campaign_complete(counts):
        reasons.append("campaign_policy_incomplete")
    return tuple(reasons)


def _campaign_status(
    results: Sequence[ReliabilityCaseResult], counts: Mapping[str, int]
) -> ReliabilityStatus:
    reasons = _campaign_reason_codes(results, counts)
    defects = {
        "required_execution_error",
        "required_truth_known_failed",
        "required_mutation_missed",
        "required_replay_verdict_failed",
        "required_replay_inconsistent",
    }
    if any(reason in defects for reason in reasons):
        return ReliabilityStatus.DEGRADED
    if _campaign_complete(counts):
        return ReliabilityStatus.CHARACTERIZED
    return ReliabilityStatus.UNCHARACTERIZED


@dataclass(frozen=True, slots=True)
class ReliabilityCampaignReceipt:
    """A self-validating, aggregate view of one reliability campaign."""

    receipt_id: str
    schema_version: str
    verifier_descriptor_hash: str
    implementation_identity_hash: str
    ordered_case_hashes: tuple[str, ...]
    campaign_policy_hash: str
    case_results: tuple[ReliabilityCaseResult, ...]
    truth_known_cases: int
    correct_cases: int
    incorrect_cases: int
    unknown_cases: int
    error_cases: int
    mutation_cases: int
    mutations_detected: int
    replay_cases: int
    replay_consistent: int
    adversarial_cases: int
    adversarial_detected: int
    reason_codes: tuple[str, ...]
    domain_id: str = "campaign"
    campaign_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_case_hashes", tuple(self.ordered_case_hashes))
        object.__setattr__(self, "case_results", tuple(self.case_results))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "campaign_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "verifier_descriptor_hash": self.verifier_descriptor_hash,
            "implementation_identity_hash": self.implementation_identity_hash,
            "ordered_case_hashes": self.ordered_case_hashes,
            "campaign_policy_hash": self.campaign_policy_hash,
            "case_results": self.case_results,
            "truth_known_cases": self.truth_known_cases,
            "correct_cases": self.correct_cases,
            "incorrect_cases": self.incorrect_cases,
            "unknown_cases": self.unknown_cases,
            "error_cases": self.error_cases,
            "mutation_cases": self.mutation_cases,
            "mutations_detected": self.mutations_detected,
            "replay_cases": self.replay_cases,
            "replay_consistent": self.replay_consistent,
            "adversarial_cases": self.adversarial_cases,
            "adversarial_detected": self.adversarial_detected,
            "reason_codes": self.reason_codes,
            "domain_id": self.domain_id,
        }

    def validate(self) -> bool:
        if self.campaign_hash != canonical_sha256(self.canonical_payload()):
            return False
        if (
            len(self.case_results) != len(self.ordered_case_hashes)
            or len(set(self.ordered_case_hashes)) != len(self.ordered_case_hashes)
            or tuple(result.case_hash for result in self.case_results)
            != self.ordered_case_hashes
            or not all(result.validate() for result in self.case_results)
        ):
            return False
        counts = _count_receipt_results(self.case_results)
        if any(getattr(self, field_name) != value for field_name, value in counts.items()):
            return False
        return self.reason_codes == _campaign_reason_codes(self.case_results, counts)


def derive_reliability_profile(
    receipt: ReliabilityCampaignReceipt,
    *,
    profile_id: str | None = None,
    domain_id: str | None = None,
) -> VerifierReliabilityProfile:
    """Build the only authoritative M6A-1 profile representation.

    Rebuilding the profile from the receipt gives validation a canonical target
    and prevents a manually chosen summary/counter set from passing merely
    because it cites an existing campaign hash.
    """

    if not receipt.validate():
        raise ValueError("genesis_reliability_campaign_receipt_invalid")
    counts = _count_receipt_results(receipt.case_results)
    return VerifierReliabilityProfile(
        profile_id=profile_id or f"profile-{receipt.verifier_descriptor_hash}",
        verifier_descriptor_hash=receipt.verifier_descriptor_hash,
        domain_id=domain_id if domain_id is not None else receipt.domain_id,
        truth_known_cases=counts["truth_known_cases"],
        correct_cases=counts["correct_cases"],
        incorrect_cases=counts["incorrect_cases"],
        unknown_cases=counts["unknown_cases"],
        error_cases=counts["error_cases"],
        mutation_cases=counts["mutation_cases"],
        mutations_detected=counts["mutations_detected"],
        replay_cases=counts["replay_cases"],
        replay_consistent=counts["replay_consistent"],
        adversarial_cases=counts["adversarial_cases"],
        adversarial_detected=counts["adversarial_detected"],
        status=_campaign_status(receipt.case_results, counts),
        campaign_receipt_hash=receipt.campaign_hash,
        implementation_identity_hash=receipt.implementation_identity_hash,
        reason_codes=receipt.reason_codes,
    )


def validate_profile_binding(
    profile: VerifierReliabilityProfile,
    receipt: ReliabilityCampaignReceipt,
    descriptor_hash: str,
    implementation_identity_hash: str,
) -> bool:
    """Verify profile provenance, not just equality of supplied hash strings."""

    if not profile.validate() or not receipt.validate():
        return False
    if (
        profile.campaign_receipt_hash != receipt.campaign_hash
        or receipt.verifier_descriptor_hash != descriptor_hash
        or profile.verifier_descriptor_hash != descriptor_hash
        or receipt.implementation_identity_hash != implementation_identity_hash
        or profile.implementation_identity_hash != implementation_identity_hash
    ):
        return False
    expected = derive_reliability_profile(
        receipt,
        profile_id=profile.profile_id,
        domain_id=profile.domain_id,
    )
    return profile.profile_hash == expected.profile_hash


def _semantic_result_hash(receipt: VerifierReceipt) -> str:
    """Hash scientific outcome, excluding operational receipt identifiers."""

    return canonical_sha256(
        {
            "status": receipt.status.value,
            "evidence": receipt.evidence,
            "counterexamples": receipt.counterexamples,
            "coverage": receipt.coverage,
            "assumptions_active": receipt.assumptions_active,
        }
    )


def _validate_verifier_receipt(
    receipt: VerifierReceipt,
    *,
    claim_hash: str,
    descriptor: VerifierDescriptor,
) -> None:
    if not isinstance(receipt, VerifierReceipt):
        raise ValueError("genesis_reliability_verifier_receipt_invalid")
    if receipt.receipt_hash != canonical_sha256(receipt.canonical_payload()):
        raise ValueError("genesis_reliability_verifier_receipt_hash_invalid")
    if receipt.claim_hash != claim_hash:
        raise ValueError("genesis_reliability_verifier_receipt_claim_mismatch")
    if (
        receipt.verifier_id != descriptor.verifier_id
        or receipt.verifier_version != descriptor.verifier_version
    ):
        raise ValueError("genesis_reliability_descriptor_receipt_mismatch")


def _execution_error_receipt(
    *,
    claim: TypedClaim,
    descriptor: VerifierDescriptor,
    context: Mapping[str, Any],
    suffix: str,
    exc: Exception,
) -> VerifierReceipt:
    return VerifierReceipt(
        receipt_id=f"reliability-execution-error-{claim.claim_hash}-{suffix}",
        schema_version="genesis-reliability-campaign-v1",
        claim_hash=claim.claim_hash,
        plan_hash=str(context.get("plan_hash", "")),
        snapshot_hash=str(context.get("snapshot_hash", "")),
        verifier_id=descriptor.verifier_id,
        verifier_version=descriptor.verifier_version,
        status=ReceiptStatus.ERROR,
        evidence={"reason": "verifier_execution_exception", "exception": type(exc).__name__},
        counterexamples=(),
        coverage={"checked": 0, "total": 0},
        assumptions_active=claim.assumptions,
        cost={},
    )


def _execute_once(
    execution: ReliabilityExecution,
    *,
    descriptor: VerifierDescriptor,
    suffix: str,
) -> VerifierReceipt:
    try:
        receipt = execution.verifier.verify(
            execution.claim,
            execution.candidate,
            execution.context,
        )
    except Exception as exc:  # Campaign evidence must record verifier crashes.
        receipt = _execution_error_receipt(
            claim=execution.claim,
            descriptor=descriptor,
            context=execution.context,
            suffix=suffix,
            exc=exc,
        )
    _validate_verifier_receipt(
        receipt,
        claim_hash=execution.claim.claim_hash,
        descriptor=descriptor,
    )
    return receipt


class VerifierReliabilityCampaign:
    """Execute presealed cases and derive a self-validating profile."""

    def run(
        self,
        *,
        receipt_id: str,
        descriptor: VerifierDescriptor,
        implementation_identity_hash: str,
        cases: Sequence[ReliabilityCase],
        executions: Mapping[
            str,
            ReliabilityExecution | tuple[Any, Any, Mapping[str, Any]],
        ],
        campaign_policy_hash: str,
    ) -> tuple[ReliabilityCampaignReceipt, VerifierReliabilityProfile]:
        if implementation_identity_hash != descriptor.implementation_identity_hash:
            raise ValueError("genesis_reliability_descriptor_implementation_mismatch")

        ordered_cases = tuple(sorted(cases, key=lambda case: case.case_hash))
        if len({case.case_hash for case in ordered_cases}) != len(ordered_cases):
            raise ValueError("genesis_reliability_case_duplicate")

        results: list[ReliabilityCaseResult] = []
        for case in ordered_cases:
            if not case.validate():
                raise ValueError("genesis_reliability_case_hash_invalid")
            if case.case_hash not in executions:
                raise ValueError("genesis_reliability_execution_missing")
            raw_execution = executions[case.case_hash]
            execution = (
                raw_execution
                if isinstance(raw_execution, ReliabilityExecution)
                else ReliabilityExecution.from_legacy_tuple(raw_execution)
            )
            self._validate_case_execution(case, execution, descriptor)

            first_receipt = _execute_once(
                execution,
                descriptor=descriptor,
                suffix=f"{case.case_hash}-first",
            )
            first_semantic_hash = _semantic_result_hash(first_receipt)
            replay_semantic_hash: str | None = None
            replay_receipt_hash: str | None = None
            replay_consistent: bool | None = None
            if case.case_class is ReliabilityCaseClass.REPLAY:
                second_receipt = _execute_once(
                    execution,
                    descriptor=descriptor,
                    suffix=f"{case.case_hash}-replay",
                )
                replay_semantic_hash = _semantic_result_hash(second_receipt)
                replay_receipt_hash = second_receipt.receipt_hash
                replay_consistent = replay_semantic_hash == first_semantic_hash

            correct = first_receipt.status is case.expected_verdict
            results.append(
                ReliabilityCaseResult(
                    case_hash=case.case_hash,
                    expected_verdict=case.expected_verdict,
                    observed_verdict=first_receipt.status,
                    verifier_receipt_hash=first_receipt.receipt_hash,
                    semantic_result_hash=first_semantic_hash,
                    correct=correct,
                    reason_codes=()
                    if correct
                    else ("expected_verdict_mismatch",),
                    case_class=case.case_class,
                    replay_semantic_result_hash=replay_semantic_hash,
                    replay_verifier_receipt_hash=replay_receipt_hash,
                    replay_consistent=replay_consistent,
                )
            )

        counts = _count_receipt_results(results)
        domain_id = canonical_sha256(
            {
                "domain_hashes": tuple(
                    sorted(case.domain_hash for case in ordered_cases)
                )
            }
        )
        receipt = ReliabilityCampaignReceipt(
            receipt_id=receipt_id,
            schema_version="genesis.m6a1",
            verifier_descriptor_hash=descriptor.descriptor_hash,
            implementation_identity_hash=implementation_identity_hash,
            ordered_case_hashes=tuple(case.case_hash for case in ordered_cases),
            campaign_policy_hash=campaign_policy_hash,
            case_results=tuple(results),
            truth_known_cases=counts["truth_known_cases"],
            correct_cases=counts["correct_cases"],
            incorrect_cases=counts["incorrect_cases"],
            unknown_cases=counts["unknown_cases"],
            error_cases=counts["error_cases"],
            mutation_cases=counts["mutation_cases"],
            mutations_detected=counts["mutations_detected"],
            replay_cases=counts["replay_cases"],
            replay_consistent=counts["replay_consistent"],
            adversarial_cases=counts["adversarial_cases"],
            adversarial_detected=counts["adversarial_detected"],
            reason_codes=_campaign_reason_codes(results, counts),
            domain_id=domain_id,
        )
        return receipt, derive_reliability_profile(receipt)

    @staticmethod
    def _validate_case_execution(
        case: ReliabilityCase,
        execution: ReliabilityExecution,
        descriptor: VerifierDescriptor,
    ) -> None:
        if execution.claim.claim_hash != case.claim_hash:
            raise ValueError("genesis_reliability_case_claim_mismatch")
        if execution.candidate_identity_hash != case.candidate_identity_hash:
            raise ValueError("genesis_reliability_case_candidate_mismatch")
        if execution.context_hash != case.context_hash:
            raise ValueError("genesis_reliability_case_context_mismatch")
        if canonical_sha256(execution.claim.domain) != case.domain_hash:
            raise ValueError("genesis_reliability_case_domain_mismatch")
        if (
            getattr(execution.verifier, "verifier_id", None) != descriptor.verifier_id
            or getattr(execution.verifier, "verifier_version", None)
            != descriptor.verifier_version
        ):
            raise ValueError("genesis_reliability_execution_descriptor_mismatch")
