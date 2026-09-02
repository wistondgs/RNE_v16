from __future__ import annotations

import pytest

from lab.genesis.evidence.events import EvidenceEvent
from lab.genesis.evidence.ledger import EvidenceLedger
from lab.genesis.evidence.seals import LedgerSeal


def event(sequence: int, parent_hash: str | None, event_id: str) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id, schema_version="m3", subject_id="claim-1", event_type="artifact",
        artifact_hash="a" * 64, receipt_hash="b" * 64, parent_hash=parent_hash,
        sequence=sequence, producer="test",
    )


def test_ledger_requires_strict_append_and_idempotent_replay():
    ledger = EvidenceLedger("ledger-1", "claim-1")
    first = event(0, None, "e0")
    assert ledger.append(first)
    assert not ledger.append(first)
    with pytest.raises(ValueError, match="sequence_not_next"):
        ledger.append(event(2, first.event_hash, "gap"))
    with pytest.raises(ValueError, match="parent_not_head"):
        ledger.append(event(1, None, "wrong-parent"))
    with pytest.raises(ValueError, match="duplicate_sequence"):
        ledger.append(event(0, None, "rewrite"))


def test_ledger_seal_detects_valid_tail_truncation_and_mutation():
    ledger = EvidenceLedger("ledger-1", "claim-1")
    first = event(0, None, "e0")
    second = event(1, first.event_hash, "e1")
    ledger.append(first)
    ledger.append(second)
    seal = LedgerSeal.seal(ledger)

    assert seal.verify_against(ledger)
    assert not seal.verify_against((first,))  # a valid short chain is still a truncation
    object.__setattr__(second, "producer", "tampered")
    assert ledger.verify()
    assert not seal.verify_against(ledger)
