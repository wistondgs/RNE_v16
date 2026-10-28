"""Hash-chained evidence events without operational timestamps."""

from __future__ import annotations

from dataclasses import dataclass, field

from lab.genesis.contracts.serialization import canonical_sha256


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: str
    schema_version: str
    subject_id: str
    event_type: str
    artifact_hash: str
    receipt_hash: str
    parent_hash: str | None
    sequence: int
    producer: str
    event_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("genesis_event_sequence_negative")
        object.__setattr__(self, "event_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {"event_id": self.event_id, "schema_version": self.schema_version, "subject_id": self.subject_id, "event_type": self.event_type, "artifact_hash": self.artifact_hash, "receipt_hash": self.receipt_hash, "parent_hash": self.parent_hash, "sequence": self.sequence, "producer": self.producer}
