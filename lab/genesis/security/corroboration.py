"""Immutable corroboration contract; independence is never inferred from a claim."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import is_artifact_hash


class IndependenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    CLAIMED = "CLAIMED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CorroborationReceipt:
    receipt_id: str
    schema_version: str
    target_hash: str
    evidence_hashes: tuple[str, ...]
    producer_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    independence_status: IndependenceStatus
    verdict: str
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_hashes", tuple(self.evidence_hashes))
        object.__setattr__(self, "producer_ids", tuple(self.producer_ids))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        object.__setattr__(self, "independence_status", IndependenceStatus(self.independence_status))
        if not is_artifact_hash(self.target_hash) or any(
            not is_artifact_hash(item) for item in self.evidence_hashes
        ):
            raise ValueError("genesis_corroboration_hash_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    @property
    def independently_corroborated(self) -> bool:
        return self.independence_status is IndependenceStatus.VERIFIED

    def canonical_payload(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "target_hash": self.target_hash,
            "evidence_hashes": self.evidence_hashes,
            "producer_ids": self.producer_ids,
            "source_ids": self.source_ids,
            "independence_status": self.independence_status.value,
            "verdict": self.verdict,
        }
