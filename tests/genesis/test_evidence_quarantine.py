from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.security.corroboration import CorroborationReceipt, IndependenceStatus
from lab.genesis.security.quarantine import QuarantineHistory, QuarantineReceipt, QuarantineState


def test_quarantine_is_immutable_receipt_overlay_with_explicit_transitions(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    target = store.put({"original": "evidence"})
    evidence = store.put({"basis": "suspicion"})
    history = QuarantineHistory(target)
    suspect = QuarantineReceipt.transition(
        receipt_id="q1", schema_version="m3", target_hash=target,
        previous_state=QuarantineState.NORMAL, new_state=QuarantineState.SUSPECT,
        reason_codes=("signal",), evidence_hashes=(evidence,), producer="test",
    )
    history.append(suspect)
    quarantined = QuarantineReceipt.transition(
        receipt_id="q2", schema_version="m3", target_hash=target,
        previous_state=QuarantineState.SUSPECT, new_state=QuarantineState.QUARANTINED,
        reason_codes=("review",), evidence_hashes=(evidence,), producer="test",
        previous_receipt_hash=suspect.receipt_hash,
    )
    history.append(quarantined)
    assert history.state is QuarantineState.QUARANTINED
    assert store.get(target) == {"original": "evidence"}
    with pytest.raises(FrozenInstanceError):
        suspect.producer = "tamper"  # type: ignore[misc]
    with pytest.raises(ValueError, match="transition_invalid"):
        QuarantineReceipt.transition(
            receipt_id="bad", schema_version="m3", target_hash=target,
            previous_state=QuarantineState.REFUTED, new_state=QuarantineState.NORMAL,
            reason_codes=(), evidence_hashes=(evidence,), producer="test",
        )


def test_only_verified_corroboration_is_automatically_independent(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    target = store.put({"target": 1})
    evidence = store.put({"evidence": 1})
    receipts = [
        CorroborationReceipt("c-" + status.value, "m3", target, (evidence,), ("p",), ("s",), status, "supports")
        for status in IndependenceStatus
    ]
    assert receipts[0].independently_corroborated
    assert not receipts[1].independently_corroborated
    assert not receipts[2].independently_corroborated
