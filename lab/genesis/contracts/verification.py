"""Verification-plan contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .serialization import canonical_sha256, freeze


@dataclass(frozen=True, slots=True)
class VerificationObligation:
    obligation_id: str
    kind: str
    target: str
    required_authority: str
    allowed_verifiers: tuple[str, ...]
    failure_semantics: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_verifiers", tuple(self.allowed_verifiers))

    def canonical_payload(self) -> dict[str, Any]:
        return {"obligation_id": self.obligation_id, "kind": self.kind, "target": self.target, "required_authority": self.required_authority, "allowed_verifiers": self.allowed_verifiers, "failure_semantics": self.failure_semantics}


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    plan_id: str
    claim_hash: str
    obligations: tuple[VerificationObligation, ...]
    budget: Mapping[str, Any]
    verifier_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligations", tuple(self.obligations))
        object.__setattr__(self, "budget", freeze(self.budget))
        object.__setattr__(self, "verifier_versions", freeze(self.verifier_versions))

    def canonical_payload(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "claim_hash": self.claim_hash, "obligations": tuple(item.canonical_payload() for item in self.obligations), "budget": self.budget, "verifier_versions": self.verifier_versions}

    @property
    def plan_hash(self) -> str:
        return canonical_sha256(self.canonical_payload())
