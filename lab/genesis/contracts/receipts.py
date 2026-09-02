"""Immutable verifier receipts; UNKNOWN is never success."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .serialization import canonical_sha256, freeze


class ReceiptStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class VerifierReceipt:
    receipt_id: str
    schema_version: str
    claim_hash: str
    plan_hash: str
    snapshot_hash: str
    verifier_id: str
    verifier_version: str
    status: ReceiptStatus
    evidence: Mapping[str, Any]
    counterexamples: tuple[Mapping[str, Any], ...]
    coverage: Mapping[str, Any]
    assumptions_active: tuple[str, ...]
    cost: Mapping[str, Any]
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ReceiptStatus(self.status))
        object.__setattr__(self, "evidence", freeze(self.evidence))
        object.__setattr__(self, "counterexamples", tuple(freeze(item) for item in self.counterexamples))
        object.__setattr__(self, "coverage", freeze(self.coverage))
        object.__setattr__(self, "assumptions_active", tuple(self.assumptions_active))
        object.__setattr__(self, "cost", freeze(self.cost))
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, "schema_version": self.schema_version, "claim_hash": self.claim_hash, "plan_hash": self.plan_hash, "snapshot_hash": self.snapshot_hash, "verifier_id": self.verifier_id, "verifier_version": self.verifier_version, "status": self.status.value, "evidence": self.evidence, "counterexamples": self.counterexamples, "coverage": self.coverage, "assumptions_active": self.assumptions_active, "cost": self.cost}
