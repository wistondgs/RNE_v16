"""Seals bind a particular complete evidence-ledger view."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.events import EvidenceEvent
from lab.genesis.evidence.ledger import EvidenceLedger


@dataclass(frozen=True, slots=True)
class LedgerSeal:
    ledger_id: str
    subject_id: str
    schema_version: str
    head_hash: str | None
    event_count: int
    sequence_max: int | None
    seal_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.event_count < 0:
            raise ValueError("genesis_seal_count_negative")
        if self.event_count == 0 and self.sequence_max is not None:
            raise ValueError("genesis_seal_empty_sequence")
        if self.event_count and self.sequence_max != self.event_count - 1:
            raise ValueError("genesis_seal_sequence_count_mismatch")
        object.__setattr__(self, "seal_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ledger_id": self.ledger_id,
            "subject_id": self.subject_id,
            "schema_version": self.schema_version,
            "head_hash": self.head_hash,
            "event_count": self.event_count,
            "sequence_max": self.sequence_max,
        }

    @classmethod
    def seal(cls, ledger: EvidenceLedger, schema_version: str = "genesis.m3") -> "LedgerSeal":
        events = ledger.events
        return cls(
            ledger_id=ledger.ledger_id,
            subject_id=ledger.subject_id,
            schema_version=schema_version,
            head_hash=events[-1].event_hash if events else None,
            event_count=len(events),
            sequence_max=events[-1].sequence if events else None,
        )

    def verify_against(self, ledger: EvidenceLedger | Sequence[EvidenceEvent]) -> bool:
        if self.seal_hash != canonical_sha256(self.canonical_payload()):
            return False
        if isinstance(ledger, EvidenceLedger):
            if ledger.ledger_id != self.ledger_id or ledger.subject_id != self.subject_id:
                return False
            events = ledger.events
            ledger_reasons = ledger.verify(events)
        else:
            events = tuple(ledger)
            ledger_reasons: list[str] = []
            parent: str | None = None
            for index, event in enumerate(events):
                if event.event_hash != canonical_sha256(event.canonical_payload()):
                    ledger_reasons.append(f"event_hash_invalid:{index}")
                if event.sequence != index:
                    ledger_reasons.append(f"event_sequence_invalid:{index}")
                if event.parent_hash != parent:
                    ledger_reasons.append(f"event_parent_invalid:{index}")
                parent = event.event_hash
        if ledger_reasons:
            return False
        head = events[-1].event_hash if events else None
        maximum = events[-1].sequence if events else None
        return (head, len(events), maximum) == (
            self.head_hash,
            self.event_count,
            self.sequence_max,
        )
