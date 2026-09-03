"""Pure, sealed roots for replayable epistemic evidence traces.

The closure is deliberately outside the ledger it commits.  It is a
content-addressed commit marker, not another mutable ledger event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from lab.genesis.contracts.serialization import canonical_sha256
from .artifacts import is_artifact_hash
from .events import EvidenceEvent
from .ledger import EvidenceLedger
from .seals import LedgerSeal


TRACE_SCHEMA_VERSION = "genesis-sealed-evidence-trace-v1"


def derive_trace_id(*, schema_version: str, federation_plan_hash: str,
                    requirement_hash: str, execution_subject_hash: str,
                    evidence_bundle_hash: str,
                    adjudication_receipt_hash: str) -> str:
    """Stable identity for one concrete M6 adjudication trace."""
    return canonical_sha256({
        "schema_version": schema_version,
        "federation_plan_hash": federation_plan_hash,
        "requirement_hash": requirement_hash,
        "execution_subject_hash": execution_subject_hash,
        "evidence_bundle_hash": evidence_bundle_hash,
        "adjudication_receipt_hash": adjudication_receipt_hash,
    })


@dataclass(frozen=True, slots=True)
class TraceArtifactGroup:
    """Canonical, role-indexed historical artifacts required for replay."""
    role: str
    artifact_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_hashes", tuple(sorted(self.artifact_hashes)))
        if not self.role or not all(is_artifact_hash(value) for value in self.artifact_hashes):
            raise ValueError("genesis_trace_closure_artifact_invalid")
        if len(set(self.artifact_hashes)) != len(self.artifact_hashes):
            raise ValueError("genesis_trace_closure_artifact_duplicate")

    def canonical_payload(self) -> dict[str, object]:
        return {"role": self.role, "artifact_hashes": self.artifact_hashes}


@dataclass(frozen=True, slots=True)
class TraceClosureManifest:
    """Outer, immutable admission root for a sealed M6 evidence transcript."""
    schema_version: str
    trace_id: str
    federation_plan_hash: str
    requirement_hash: str
    execution_subject_hash: str
    evidence_bundle_hash: str
    adjudication_receipt_hash: str
    artifact_groups: tuple[TraceArtifactGroup, ...]
    ordered_ledger_event_artifact_hashes: tuple[str, ...]
    ordered_ledger_event_hashes: tuple[str, ...]
    ledger_head_hash: str | None
    ledger_event_count: int
    ledger_seal_artifact_hash: str
    provenance_node_artifact_hashes: tuple[str, ...]
    provenance_edge_artifact_hashes: tuple[str, ...]
    closure_hash: str = field(init=False)

    def __post_init__(self) -> None:
        groups = tuple(sorted((TraceArtifactGroup(item.role, item.artifact_hashes)
                               for item in self.artifact_groups), key=lambda item: item.role))
        object.__setattr__(self, "artifact_groups", groups)
        for name in ("ordered_ledger_event_artifact_hashes", "ordered_ledger_event_hashes",
                     "provenance_node_artifact_hashes", "provenance_edge_artifact_hashes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self._structurally_valid():
            raise ValueError("genesis_trace_closure_invalid")
        object.__setattr__(self, "closure_hash", canonical_sha256(self.canonical_payload()))
        if self.closure_hash in self.ordered_ledger_event_artifact_hashes:
            raise ValueError("genesis_trace_closure_self_ledger_event")

    @property
    def ledger_id(self) -> str:
        return f"genesis-m6b4:{self.trace_id}"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "federation_plan_hash": self.federation_plan_hash,
            "requirement_hash": self.requirement_hash,
            "execution_subject_hash": self.execution_subject_hash,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "adjudication_receipt_hash": self.adjudication_receipt_hash,
            "artifact_groups": tuple(item.canonical_payload() for item in self.artifact_groups),
            "ordered_ledger_event_artifact_hashes": self.ordered_ledger_event_artifact_hashes,
            "ordered_ledger_event_hashes": self.ordered_ledger_event_hashes,
            "ledger_head_hash": self.ledger_head_hash,
            "ledger_event_count": self.ledger_event_count,
            "ledger_seal_artifact_hash": self.ledger_seal_artifact_hash,
            "provenance_node_artifact_hashes": self.provenance_node_artifact_hashes,
            "provenance_edge_artifact_hashes": self.provenance_edge_artifact_hashes,
        }

    def _structurally_valid(self) -> bool:
        primary = (self.federation_plan_hash, self.requirement_hash,
                   self.execution_subject_hash, self.evidence_bundle_hash,
                   self.adjudication_receipt_hash, self.ledger_seal_artifact_hash)
        all_hashes = (*primary, *self.ordered_ledger_event_artifact_hashes,
                      *self.ordered_ledger_event_hashes,
                      *self.provenance_node_artifact_hashes,
                      *self.provenance_edge_artifact_hashes)
        if (not self.schema_version or not all(is_artifact_hash(value) for value in all_hashes)
                or self.ledger_event_count < 0
                or len(self.ordered_ledger_event_hashes) != self.ledger_event_count
                or len(self.ordered_ledger_event_artifact_hashes) != self.ledger_event_count):
            return False
        if self.ledger_event_count == 0:
            if self.ledger_head_hash is not None:
                return False
        elif self.ledger_head_hash != self.ordered_ledger_event_hashes[-1]:
            return False
        if self.ledger_seal_artifact_hash in self.ordered_ledger_event_artifact_hashes:
            return False
        if len({item.role for item in self.artifact_groups}) != len(self.artifact_groups):
            return False
        if self.trace_id != derive_trace_id(
            schema_version=self.schema_version,
            federation_plan_hash=self.federation_plan_hash,
            requirement_hash=self.requirement_hash,
            execution_subject_hash=self.execution_subject_hash,
            evidence_bundle_hash=self.evidence_bundle_hash,
            adjudication_receipt_hash=self.adjudication_receipt_hash,
        ):
            return False
        return True

    def validate(self) -> bool:
        return (self._structurally_valid()
                and self.closure_hash == canonical_sha256(self.canonical_payload())
                and self.closure_hash not in self.ordered_ledger_event_artifact_hashes)

    def referenced_artifact_hashes(self) -> tuple[str, ...]:
        hashes = [self.federation_plan_hash, self.requirement_hash,
                  self.execution_subject_hash, self.evidence_bundle_hash,
                  self.adjudication_receipt_hash, self.ledger_seal_artifact_hash]
        hashes.extend(self.ordered_ledger_event_artifact_hashes)
        # ``EvidenceEvent.event_hash`` is the canonical payload hash, hence it
        # is also the CAS identity of the persisted transcript event.
        hashes.extend(self.ordered_ledger_event_hashes)
        hashes.extend(self.provenance_node_artifact_hashes)
        hashes.extend(self.provenance_edge_artifact_hashes)
        for group in self.artifact_groups:
            hashes.extend(group.artifact_hashes)
        return tuple(sorted(set(hashes)))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TraceClosureManifest":
        """Rehydrate only the sealed, canonical fields stored in CAS."""
        return cls(
            schema_version=str(payload["schema_version"]),
            trace_id=str(payload["trace_id"]),
            federation_plan_hash=str(payload["federation_plan_hash"]),
            requirement_hash=str(payload["requirement_hash"]),
            execution_subject_hash=str(payload["execution_subject_hash"]),
            evidence_bundle_hash=str(payload["evidence_bundle_hash"]),
            adjudication_receipt_hash=str(payload["adjudication_receipt_hash"]),
            artifact_groups=tuple(
                TraceArtifactGroup(str(item["role"]), tuple(item["artifact_hashes"]))
                for item in payload["artifact_groups"]
            ),
            ordered_ledger_event_artifact_hashes=tuple(payload["ordered_ledger_event_artifact_hashes"]),
            ordered_ledger_event_hashes=tuple(payload["ordered_ledger_event_hashes"]),
            ledger_head_hash=payload["ledger_head_hash"],
            ledger_event_count=int(payload["ledger_event_count"]),
            ledger_seal_artifact_hash=str(payload["ledger_seal_artifact_hash"]),
            provenance_node_artifact_hashes=tuple(payload["provenance_node_artifact_hashes"]),
            provenance_edge_artifact_hashes=tuple(payload["provenance_edge_artifact_hashes"]),
        )


def verify_trace_closure(closure: TraceClosureManifest, *,
                         artifact_payloads: Mapping[str, Any],
                         events: Sequence[EvidenceEvent],
                         seal: LedgerSeal,
                         expected_closure_hash: str | None = None) -> tuple[str, ...]:
    """Verify a closure without any CAS or process-local ledger dependency."""
    reasons: list[str] = []
    if not closure.validate():
        reasons.append("closure_hash_invalid")
    if expected_closure_hash is not None and closure.closure_hash != expected_closure_hash:
        reasons.append("closure_root_mismatch")
    for artifact_hash in closure.referenced_artifact_hashes():
        payload = artifact_payloads.get(artifact_hash)
        if payload is None:
            reasons.append(f"artifact_missing:{artifact_hash}")
        elif canonical_sha256(payload) != artifact_hash:
            reasons.append(f"artifact_hash_invalid:{artifact_hash}")
    observed = tuple(events)
    if tuple(event.event_hash for event in observed) != closure.ordered_ledger_event_hashes:
        reasons.append("ledger_event_order_invalid")
    if tuple(canonical_sha256(event.canonical_payload()) for event in observed) != closure.ordered_ledger_event_hashes:
        reasons.append("ledger_event_hash_invalid")
    if tuple(event.artifact_hash for event in observed) != closure.ordered_ledger_event_artifact_hashes:
        reasons.append("ledger_event_artifact_binding_invalid")
    if len(observed) != closure.ledger_event_count:
        reasons.append("ledger_event_count_invalid")
    ledger = EvidenceLedger(closure.ledger_id, closure.trace_id)
    for event in observed:
        try:
            ledger.append(event)
        except ValueError as error:
            reasons.append(f"ledger:{error}")
    if ledger.head_hash != closure.ledger_head_hash:
        reasons.append("ledger_head_invalid")
    if seal.seal_hash != closure.ledger_seal_artifact_hash:
        reasons.append("ledger_seal_binding_invalid")
    if canonical_sha256(seal.canonical_payload()) != closure.ledger_seal_artifact_hash:
        reasons.append("ledger_seal_hash_invalid")
    if not seal.verify_against(ledger):
        reasons.append("ledger_seal_invalid")
    return tuple(reasons)
