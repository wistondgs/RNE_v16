"""Hash-sealed reliability summaries for Genesis verifiers.

The profile deliberately contains only the summary. A conclusive profile is
usable only together with the campaign receipt from which it was derived;
``validate_profile_binding`` in ``reliability_campaign`` verifies that link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lab.genesis.contracts.serialization import canonical_sha256


class ReliabilityStatus(str, Enum):
    UNCHARACTERIZED = "UNCHARACTERIZED"
    CHARACTERIZED = "CHARACTERIZED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class VerifierReliabilityProfile:
    """A campaign-derived summary of reliability in one declared domain.

    ``UNCHARACTERIZED`` is allowed as a provisional/manual description. The
    two conclusive states require both campaign and implementation bindings so
    neither a label nor a descriptor name can manufacture authority.
    """

    profile_id: str
    verifier_descriptor_hash: str
    domain_id: str
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
    status: ReliabilityStatus
    campaign_receipt_hash: str | None = None
    implementation_identity_hash: str | None = None
    reason_codes: tuple[str, ...] = ()
    profile_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ReliabilityStatus(self.status))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        if self.status in {
            ReliabilityStatus.CHARACTERIZED,
            ReliabilityStatus.DEGRADED,
        } and (
            self.campaign_receipt_hash is None
            or self.implementation_identity_hash is None
        ):
            raise ValueError("genesis_reliability_profile_campaign_binding_required")
        object.__setattr__(self, "profile_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "verifier_descriptor_hash": self.verifier_descriptor_hash,
            "domain_id": self.domain_id,
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
            "status": self.status.value,
            "campaign_receipt_hash": self.campaign_receipt_hash,
            "implementation_identity_hash": self.implementation_identity_hash,
            "reason_codes": self.reason_codes,
        }

    def validate(self) -> bool:
        """Check seal and locally checkable counter invariants.

        This does not prove campaign provenance; that needs the campaign
        receipt and is intentionally a separate validation step.
        """

        counters = (
            self.truth_known_cases,
            self.correct_cases,
            self.incorrect_cases,
            self.unknown_cases,
            self.error_cases,
            self.mutation_cases,
            self.mutations_detected,
            self.replay_cases,
            self.replay_consistent,
            self.adversarial_cases,
            self.adversarial_detected,
        )
        return (
            self.profile_hash == canonical_sha256(self.canonical_payload())
            and all(isinstance(value, int) and value >= 0 for value in counters)
            and self.correct_cases + self.incorrect_cases == self.truth_known_cases
            and self.mutations_detected <= self.mutation_cases
            and self.replay_consistent <= self.replay_cases
            and self.adversarial_detected <= self.adversarial_cases
        )
