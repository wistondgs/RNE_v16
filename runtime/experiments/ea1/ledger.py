from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from runtime.storage import StorageFacade

from .canonical import canonical_value, digest, stable_id

EVENT_TYPE = "ea1.experimental.event"
SOURCE = "ea1_neutral_substrate"


class LedgerIntegrityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    event_id: str
    run_id: str
    arm: str
    sequence: int
    logical_time: int
    kind: str
    artifact_id: str
    artifact_hash: str
    previous_hash: str
    payload: Mapping[str, Any]
    entry_hash: str

    def core_payload(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "run_id": self.run_id, "arm": self.arm, "sequence": self.sequence, "logical_time": self.logical_time, "kind": self.kind, "artifact_id": self.artifact_id, "artifact_hash": self.artifact_hash, "previous_hash": self.previous_hash, "payload": dict(self.payload)}

    def to_payload(self) -> dict[str, Any]:
        return {**self.core_payload(), "entry_hash": self.entry_hash}

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> "LedgerEntry":
        entry = cls(
            event_id=str(raw["event_id"]), run_id=str(raw["run_id"]), arm=str(raw["arm"]),
            sequence=int(raw["sequence"]), logical_time=int(raw["logical_time"]), kind=str(raw["kind"]),
            artifact_id=str(raw["artifact_id"]), artifact_hash=str(raw["artifact_hash"]),
            previous_hash=str(raw["previous_hash"]), payload=dict(raw["payload"]), entry_hash=str(raw["entry_hash"]),
        )
        if digest(entry.core_payload()) != entry.entry_hash or digest(entry.payload) != entry.artifact_hash:
            raise LedgerIntegrityError("ledger_hash_mismatch")
        return entry


class LedgerBackend(Protocol):
    def load(self, run_id: str) -> list[Mapping[str, Any]]: ...
    def append(self, run_id: str, event_id: str, payload: Mapping[str, Any]) -> None: ...


class InMemoryLedgerBackend:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def load(self, run_id: str) -> list[Mapping[str, Any]]:
        return [row for row in self.rows if row["run_id"] == run_id]

    def append(self, run_id: str, event_id: str, payload: Mapping[str, Any]) -> None:
        self.rows.append(dict(payload))


class StorageLedgerBackend:
    def __init__(self, storage: StorageFacade) -> None:
        self.storage = storage

    def load(self, run_id: str) -> list[Mapping[str, Any]]:
        events = self.storage.list_events(run_id=run_id, event_types=[EVENT_TYPE], limit=10000)
        return [event.payload for event in events]

    def append(self, run_id: str, event_id: str, payload: Mapping[str, Any]) -> None:
        self.storage.append_event(event_type=EVENT_TYPE, payload=payload, run_id=run_id, source=SOURCE, event_id=event_id)


class ExperimentLedger:
    """Append-only, hash-chained and replay-idempotent experimental ledger."""

    def __init__(self, backend: LedgerBackend | None = None) -> None:
        self.backend = backend or InMemoryLedgerBackend()
        self._quarantined: set[str] = set()

    def entries(self, run_id: str) -> tuple[LedgerEntry, ...]:
        try:
            entries = [LedgerEntry.from_payload(row) for row in self.backend.load(run_id)]
            entries.sort(key=lambda item: item.sequence)
            previous = "GENESIS"
            for sequence, entry in enumerate(entries):
                if entry.run_id != run_id or entry.sequence != sequence or entry.logical_time < sequence or entry.previous_hash != previous:
                    raise LedgerIntegrityError("ledger_chain_invalid")
                previous = entry.entry_hash
            return tuple(entries)
        except (KeyError, TypeError, ValueError) as exc:
            self._quarantined.add(run_id)
            if isinstance(exc, LedgerIntegrityError):
                raise
            raise LedgerIntegrityError("ledger_row_invalid") from exc

    def append(self, *, run_id: str, arm: str, logical_time: int, kind: str, artifact: Any) -> tuple[LedgerEntry, bool]:
        if run_id in self._quarantined:
            raise LedgerIntegrityError("run_quarantined")
        payload = canonical_value(artifact.to_payload())
        artifact_id = next((str(payload[key]) for key in payload if key.endswith("_id")), "")
        if not artifact_id:
            raise LedgerIntegrityError("artifact_identity_required")
        event_id = stable_id("ea1e", {"run_id": run_id, "arm": arm, "kind": kind, "artifact_id": artifact_id})
        current = self.entries(run_id)
        replay = next((entry for entry in current if entry.event_id == event_id), None)
        payload_hash = digest(payload)
        if replay:
            if replay.artifact_hash != payload_hash:
                self._quarantined.add(run_id)
                raise LedgerIntegrityError("divergent_replay")
            return replay, False
        if logical_time < len(current):
            raise LedgerIntegrityError("logical_time_regression")
        core = {"event_id": event_id, "run_id": run_id, "arm": arm, "sequence": len(current), "logical_time": logical_time, "kind": kind, "artifact_id": artifact_id, "artifact_hash": payload_hash, "previous_hash": current[-1].entry_hash if current else "GENESIS", "payload": payload}
        entry = LedgerEntry(**core, entry_hash=digest(core))
        self.backend.append(run_id, event_id, entry.to_payload())
        return entry, True

    def quarantined(self, run_id: str) -> bool:
        return run_id in self._quarantined
