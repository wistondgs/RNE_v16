"""Fail-closed integrity replay for Genesis artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from lab.genesis.causal.snapshot import CausalSnapshot
from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.contracts.verification import VerificationPlan
from lab.genesis.evidence.events import EvidenceEvent
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.ledger import EvidenceLedger
from lab.genesis.evidence.seals import LedgerSeal
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.risk import RiskAssessment, RiskAssessmentLedger
from lab.genesis.security.corroboration import CorroborationReceipt
from lab.genesis.security.quarantine import QuarantineHistory, QuarantineReceipt


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


@dataclass(frozen=True, slots=True)
class EvidenceReplay:
    """Fail-closed M3 replay across artifacts, ledger, provenance and overlays."""

    status: ReplayStatus
    reasons: tuple[str, ...]

    @classmethod
    def verify(
        cls,
        store: ContentAddressedArtifactStore,
        ledger: EvidenceLedger,
        seal: LedgerSeal,
        graph: ProvenanceGraph,
        risk_assessments: Iterable[RiskAssessment] = (),
        quarantine_receipts: Iterable[QuarantineReceipt] = (),
        corroboration_receipts: Iterable[CorroborationReceipt] = (),
        *,
        events: Sequence[EvidenceEvent] | None = None,
    ) -> "EvidenceReplay":
        reasons: list[str] = []
        observed_events = ledger.events if events is None else tuple(events)
        for reason in ledger.verify(observed_events):
            reasons.append(f"ledger:{reason}")
        if not seal.verify_against(observed_events):
            reasons.append("ledger:seal_invalid")
        for index, event in enumerate(observed_events):
            if not store.verify(event.artifact_hash):
                reasons.append(f"event_artifact_invalid:{index}")
        for node in graph.nodes:
            if not store.verify(node.artifact_hash):
                reasons.append(f"node_artifact_invalid:{node.node_id}")
            if not store.verify(node.metadata_hash):
                reasons.append(f"node_metadata_invalid:{node.node_id}")
        for reason in graph.verify():
            reasons.append(f"graph:{reason}")

        risk_ledger = RiskAssessmentLedger()
        for index, assessment in enumerate(risk_assessments):
            if assessment.assessment_hash != canonical_sha256(assessment.canonical_payload()):
                reasons.append(f"risk_hash_invalid:{index}")
                continue
            if assessment.target_node_id not in {node.node_id for node in graph.nodes}:
                reasons.append(f"risk_target_invalid:{index}")
            for evidence_hash in assessment.evidence_hashes:
                if not store.verify(evidence_hash):
                    reasons.append(f"risk_evidence_invalid:{index}")
            try:
                risk_ledger.append(assessment)
            except ValueError as error:
                reasons.append(f"risk:{error}")

        histories: dict[str, QuarantineHistory] = {}
        for index, receipt in enumerate(quarantine_receipts):
            if receipt.receipt_hash != canonical_sha256(receipt.canonical_payload()):
                reasons.append(f"quarantine_hash_invalid:{index}")
                continue
            if not store.verify(receipt.target_hash):
                reasons.append(f"quarantine_target_invalid:{index}")
            for evidence_hash in receipt.evidence_hashes:
                if not store.verify(evidence_hash):
                    reasons.append(f"quarantine_evidence_invalid:{index}")
            history = histories.setdefault(receipt.target_hash, QuarantineHistory(receipt.target_hash))
            try:
                history.append(receipt)
            except ValueError as error:
                reasons.append(f"quarantine:{error}")

        for index, receipt in enumerate(corroboration_receipts):
            if receipt.receipt_hash != canonical_sha256(receipt.canonical_payload()):
                reasons.append(f"corroboration_hash_invalid:{index}")
            if not store.verify(receipt.target_hash):
                reasons.append(f"corroboration_target_invalid:{index}")
            for evidence_hash in receipt.evidence_hashes:
                if not store.verify(evidence_hash):
                    reasons.append(f"corroboration_evidence_invalid:{index}")
        return cls(ReplayStatus.FAIL if reasons else ReplayStatus.PASS, tuple(reasons))
