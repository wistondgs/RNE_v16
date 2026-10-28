"""Append-only in-memory evidence ledger with hash-chain validation."""

from __future__ import annotations

from typing import Sequence

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.events import EvidenceEvent


class EvidenceLedger:
    """A ledger is a guarded append-only view, not a mutable event list."""

    def __init__(self, ledger_id: str, subject_id: str) -> None:
        self.ledger_id = ledger_id
        self.subject_id = subject_id
        self._events: tuple[EvidenceEvent, ...] = ()

    @property
    def events(self) -> tuple[EvidenceEvent, ...]:
        return self._events

    @property
    def head_hash(self) -> str | None:
        return self._events[-1].event_hash if self._events else None

    def append(self, event: EvidenceEvent) -> bool:
        """Append an event, returning False only for an identical replay."""
        if event.subject_id != self.subject_id:
            raise ValueError("genesis_ledger_subject_mismatch")
        if event.event_hash != canonical_sha256(event.canonical_payload()):
            raise ValueError("genesis_ledger_event_hash_invalid")
        for existing in self._events:
            if existing.event_hash == event.event_hash:
                if existing.canonical_payload() == event.canonical_payload():
                    return False
                raise ValueError("genesis_ledger_conflicting_duplicate")
            if existing.sequence == event.sequence:
                raise ValueError("genesis_ledger_duplicate_sequence")
        expected_sequence = len(self._events)
        expected_parent = self.head_hash
        if event.sequence != expected_sequence:
            raise ValueError("genesis_ledger_sequence_not_next")
        if event.parent_hash != expected_parent:
            raise ValueError("genesis_ledger_parent_not_head")
        self._events = (*self._events, event)
        return True

    def verify(self, events: Sequence[EvidenceEvent] | None = None) -> tuple[str, ...]:
        """Validate an observed ledger view, including all append invariants."""
        observed = self._events if events is None else tuple(events)
        reasons: list[str] = []
        parent: str | None = None
        for index, event in enumerate(observed):
            if event.event_hash != canonical_sha256(event.canonical_payload()):
                reasons.append(f"event_hash_invalid:{index}")
            if event.subject_id != self.subject_id:
                reasons.append(f"event_subject_invalid:{index}")
            if event.sequence != index:
                reasons.append(f"event_sequence_invalid:{index}")
            if event.parent_hash != parent:
                reasons.append(f"event_parent_invalid:{index}")
            parent = event.event_hash
        return tuple(reasons)
