"""Receipt-only quarantine overlay; it never edits evidence or provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import is_artifact_hash


class QuarantineState(str, Enum):
    NORMAL = "NORMAL"
    SUSPECT = "SUSPECT"
    QUARANTINED = "QUARANTINED"
    CORROBORATED = "CORROBORATED"
    REFUTED = "REFUTED"
    REHABILITATED = "REHABILITATED"


_ALLOWED_TRANSITIONS = {
    (QuarantineState.NORMAL, QuarantineState.SUSPECT),
    (QuarantineState.SUSPECT, QuarantineState.QUARANTINED),
    (QuarantineState.SUSPECT, QuarantineState.CORROBORATED),
    (QuarantineState.QUARANTINED, QuarantineState.REHABILITATED),
    (QuarantineState.QUARANTINED, QuarantineState.REFUTED),
    (QuarantineState.CORROBORATED, QuarantineState.REHABILITATED),
}


@dataclass(frozen=True, slots=True)
class QuarantineReceipt:
    receipt_id: str
    schema_version: str
    target_hash: str
    previous_state: QuarantineState
    new_state: QuarantineState
    reason_codes: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    producer: str
    previous_receipt_hash: str | None = None
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "previous_state", QuarantineState(self.previous_state))
        object.__setattr__(self, "new_state", QuarantineState(self.new_state))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "evidence_hashes", tuple(self.evidence_hashes))
        if not is_artifact_hash(self.target_hash) or any(
            not is_artifact_hash(item) for item in self.evidence_hashes
        ):
            raise ValueError("genesis_quarantine_hash_invalid")
        if (self.previous_state, self.new_state) not in _ALLOWED_TRANSITIONS:
            raise ValueError("genesis_quarantine_transition_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "target_hash": self.target_hash,
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "reason_codes": self.reason_codes,
            "evidence_hashes": self.evidence_hashes,
            "producer": self.producer,
            "previous_receipt_hash": self.previous_receipt_hash,
        }

    @classmethod
    def transition(
        cls,
        *,
        receipt_id: str,
        schema_version: str,
        target_hash: str,
        previous_state: QuarantineState,
        new_state: QuarantineState,
        reason_codes: tuple[str, ...],
        evidence_hashes: tuple[str, ...],
        producer: str,
        previous_receipt_hash: str | None = None,
    ) -> "QuarantineReceipt":
        return cls(
            receipt_id, schema_version, target_hash, previous_state, new_state,
            reason_codes, evidence_hashes, producer, previous_receipt_hash,
        )


class QuarantineHistory:
    """An append-only receipt chain for one target; state is derived from it."""

    def __init__(self, target_hash: str) -> None:
        if not is_artifact_hash(target_hash):
            raise ValueError("genesis_quarantine_hash_invalid")
        self.target_hash = target_hash
        self._receipts: tuple[QuarantineReceipt, ...] = ()

    @property
    def receipts(self) -> tuple[QuarantineReceipt, ...]:
        return self._receipts

    @property
    def state(self) -> QuarantineState:
        return self._receipts[-1].new_state if self._receipts else QuarantineState.NORMAL

    def append(self, receipt: QuarantineReceipt) -> bool:
        if receipt.target_hash != self.target_hash:
            raise ValueError("genesis_quarantine_target_mismatch")
        if receipt.receipt_hash != canonical_sha256(receipt.canonical_payload()):
            raise ValueError("genesis_quarantine_receipt_hash_invalid")
        for current in self._receipts:
            if current.receipt_hash == receipt.receipt_hash:
                if current.canonical_payload() == receipt.canonical_payload():
                    return False
                raise ValueError("genesis_quarantine_conflicting_duplicate")
        if receipt.previous_state is not self.state:
            raise ValueError("genesis_quarantine_previous_state_invalid")
        expected = self._receipts[-1].receipt_hash if self._receipts else None
        if receipt.previous_receipt_hash != expected:
            raise ValueError("genesis_quarantine_previous_receipt_invalid")
        self._receipts = (*self._receipts, receipt)
        return True
