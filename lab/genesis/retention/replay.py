"""Fail-closed replay of a retention decision against its stated M3 snapshot."""
from __future__ import annotations
from dataclasses import dataclass
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.risk import RiskAssessment
from lab.genesis.retention.epistemic import EpistemicStateRef, RetentionEpistemicView
from lab.genesis.retention.observation import RetentionObservationReceipt
from lab.genesis.retention.package import RetentionAuditPackage
from lab.genesis.retention.receipts import BaselineMeasurementReceipt, RetentionDecisionReceipt, RetentionReverificationRequest, RetentionVerdict
from lab.genesis.retention.rule_a_star import RuleAStar
from lab.genesis.security.quarantine import QuarantineReceipt

@dataclass(frozen=True, slots=True)
class RetentionReplay:
    verdict:RetentionVerdict; reasons:tuple[str,...]
    @classmethod
    def verify(cls, store:ContentAddressedArtifactStore, graph:ProvenanceGraph, package:RetentionAuditPackage, baseline:BaselineMeasurementReceipt, observation:RetentionObservationReceipt, state:EpistemicStateRef, view:RetentionEpistemicView, decision:RetentionDecisionReceipt, request:RetentionReverificationRequest|None=None, assessments:tuple[RiskAssessment,...]=(), quarantine_receipts:tuple[QuarantineReceipt,...]=())->"RetentionReplay":
        reasons=[]
        if package.validate_bindings(store,graph): reasons.extend(package.validate_bindings(store,graph))
        reasons.extend(f"graph:{reason}" for reason in graph.verify())
        for index, assessment in enumerate(assessments):
            if assessment.assessment_hash!=canonical_sha256(assessment.canonical_payload()): reasons.append(f"risk_hash_invalid:{index}")
            if any(not store.verify(value) for value in assessment.evidence_hashes): reasons.append(f"risk_evidence_invalid:{index}")
        for index, receipt in enumerate(quarantine_receipts):
            if receipt.receipt_hash!=canonical_sha256(receipt.canonical_payload()): reasons.append(f"quarantine_hash_invalid:{index}")
            if not store.verify(receipt.target_hash) or any(not store.verify(value) for value in receipt.evidence_hashes): reasons.append(f"quarantine_reference_invalid:{index}")
        for name,item,payload in (("baseline",baseline,baseline.canonical_payload()),("observation",observation,observation.canonical_payload()),("state",state,state.canonical_payload()),("view",view,view.canonical_payload()),("decision",decision,decision.canonical_payload())):
            identity=getattr(item, {"baseline":"receipt_hash","observation":"observation_hash","state":"state_hash","view":"view_hash","decision":"decision_hash"}[name])
            if identity!=canonical_sha256(payload): reasons.append(f"{name}_hash_invalid")
        current=EpistemicStateRef.from_records(graph,assessments,quarantine_receipts,schema_version=state.schema_version,corroboration_view_hash=state.corroboration_view_hash,artifact_ledger_seal_hash=state.artifact_ledger_seal_hash)
        if current.state_hash!=state.state_hash: reasons.append("epistemic_state_records_mismatch")
        try:
            materialized=RetentionEpistemicView.materialize(package,state,store,graph,assessments,quarantine_receipts)
            if materialized.view_hash!=view.view_hash: reasons.append("epistemic_view_mismatch")
        except Exception: reasons.append("epistemic_view_invalid")
        expected=RuleAStar.evaluate(package,baseline,observation,state,view,decision_id=decision.decision_id,request_id=request.request_id if request else "retention-reverify")
        if expected.decision.decision_hash!=decision.decision_hash: reasons.append("decision_recalculation_mismatch")
        if (request is None)!=(decision.reverification_request_hash is None): reasons.append("reverification_reference_invalid")
        if request and (request.request_hash!=decision.reverification_request_hash or request.request_hash!=canonical_sha256(request.canonical_payload())): reasons.append("reverification_hash_invalid")
        return cls(RetentionVerdict.ERROR if reasons else decision.verdict,tuple(reasons))
