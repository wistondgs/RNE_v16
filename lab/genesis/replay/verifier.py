"""Fail-closed integrity replay for Genesis artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from lab.genesis.causal.snapshot import CausalSnapshot
from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.contracts.verification import VerificationPlan
from lab.genesis.evidence.events import EvidenceEvent


class ReplayStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ReplayAttestation:
    status: ReplayStatus
    reasons: tuple[str, ...]

    @classmethod
    def verify(cls, claim: TypedClaim, plan: VerificationPlan, snapshot: CausalSnapshot, receipt: VerifierReceipt, events: Sequence[EvidenceEvent]) -> "ReplayAttestation":
        reasons: list[str] = []
        if claim.claim_hash != canonical_sha256(claim.canonical_payload()): reasons.append("claim_hash_invalid")
        if plan.plan_hash != canonical_sha256(plan.canonical_payload()): reasons.append("plan_hash_invalid")
        if snapshot.snapshot_hash != canonical_sha256(snapshot.canonical_payload()): reasons.append("snapshot_hash_invalid")
        if receipt.receipt_hash != canonical_sha256(receipt.canonical_payload()): reasons.append("receipt_hash_invalid")
        if plan.claim_hash != claim.claim_hash: reasons.append("plan_claim_reference_invalid")
        if snapshot.claim_hash != claim.claim_hash: reasons.append("snapshot_claim_reference_invalid")
        if receipt.claim_hash != claim.claim_hash: reasons.append("receipt_claim_reference_invalid")
        if receipt.plan_hash != plan.plan_hash: reasons.append("receipt_plan_reference_invalid")
        if receipt.snapshot_hash != snapshot.snapshot_hash: reasons.append("receipt_snapshot_reference_invalid")
        previous: str | None = None
        for index, event in enumerate(events):
            if event.event_hash != canonical_sha256(event.canonical_payload()): reasons.append(f"event_hash_invalid:{index}")
            if event.sequence != index: reasons.append(f"event_sequence_invalid:{index}")
            if event.parent_hash != previous: reasons.append(f"event_parent_invalid:{index}")
            if event.subject_id != claim.claim_id: reasons.append(f"event_subject_invalid:{index}")
            if event.receipt_hash != receipt.receipt_hash: reasons.append(f"event_receipt_reference_invalid:{index}")
            if event.artifact_hash not in {claim.claim_hash, plan.plan_hash, snapshot.snapshot_hash, receipt.receipt_hash}: reasons.append(f"event_artifact_reference_invalid:{index}")
            previous = event.event_hash
        return cls(ReplayStatus.FAIL if reasons else ReplayStatus.PASS, tuple(reasons))
