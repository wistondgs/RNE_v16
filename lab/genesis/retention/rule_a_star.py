"""Rule A*: provenance-covered retention, never a runtime rollback mechanism."""
from __future__ import annotations
from dataclasses import dataclass
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.retention.epistemic import EpistemicStateRef, RetentionEpistemicView
from lab.genesis.retention.observation import RetentionObservationReceipt
from lab.genesis.retention.package import RetentionAuditPackage, RetentionSurface
from lab.genesis.retention.receipts import BaselineMeasurementReceipt, RetentionDecisionReceipt, RetentionReverificationRequest, RetentionVerdict
from lab.genesis.security.quarantine import QuarantineState

@dataclass(frozen=True, slots=True)
class RetentionEvaluation:
    decision: RetentionDecisionReceipt
    reverification_request: RetentionReverificationRequest | None

class RuleAStar:
    """Produces a scientific verdict/receipt only; it has no promotion or rollback API."""
    acceptable_states={QuarantineState.NORMAL,QuarantineState.CORROBORATED,QuarantineState.REHABILITATED}
    @classmethod
    def evaluate(cls, package:RetentionAuditPackage, baseline:BaselineMeasurementReceipt, observation:RetentionObservationReceipt, state:EpistemicStateRef, view:RetentionEpistemicView, *, decision_id:str="retention-decision", request_id:str="retention-reverify")->RetentionEvaluation:
        reasons=[]
        if package.package_hash!=canonical_sha256(package.canonical_payload()): reasons.append("package_hash_invalid")
        if baseline.receipt_hash!=canonical_sha256(baseline.canonical_payload()): reasons.append("baseline_hash_invalid")
        if observation.observation_hash!=canonical_sha256(observation.canonical_payload()): reasons.append("observation_hash_invalid")
        if state.state_hash!=canonical_sha256(state.canonical_payload()) or view.view_hash!=canonical_sha256(view.canonical_payload()) or view.epistemic_state_hash!=state.state_hash: reasons.append("epistemic_state_invalid")
        expected=(package.capability_id,package.audit_dataset_hash,package.verifier_spec_hash,package.metric_spec_hash,package.sampling_policy_hash)
        if (baseline.capability_id,baseline.audit_dataset_hash,baseline.verifier_spec_hash,baseline.metric_spec_hash,baseline.sampling_policy_hash)!=expected: reasons.append("baseline_package_reference_invalid")
        if (observation.capability_id,observation.audit_dataset_hash,observation.verifier_spec_hash,observation.metric_spec_hash,observation.sampling_policy_hash)!=(package.capability_id,package.audit_dataset_hash,package.verifier_spec_hash,package.metric_spec_hash,package.sampling_policy_hash) or observation.package_hash!=package.package_hash: reasons.append("observation_package_reference_invalid")
        surface_hashes=[]; blocked=None
        try:
            for surface in package.critical_surfaces():
                item=view.for_surface(surface); surface_hashes.append(item.assessment_hash)
                if item.artifact_hash!=package.artifact_hash_for(surface) or item.provenance_node_id!=package.provenance_node_ids[surface.value] or not item.integrity_pass: reasons.append(f"surface_integrity_invalid:{surface.value}")
                elif item.risk_score>=package.sigma_max or item.quarantine_state not in cls.acceptable_states:
                    blocked=blocked or item
        except (StopIteration, KeyError): reasons.append("surface_assessment_missing")
        regression=max(0.0,baseline.score-observation.observed_score)
        request=None
        if reasons: verdict=RetentionVerdict.ERROR
        elif blocked is not None:
            verdict=RetentionVerdict.INCONCLUSIVE
            request=RetentionReverificationRequest(request_id,"genesis.m4",package.package_hash,blocked.surface,blocked.risk_score,blocked.quarantine_state.value,("critical_surface_untrusted",), ("verify_artifact_integrity","rebuild_provenance_covered_measurement"),state.state_hash)
            reasons=("critical_surface_untrusted",)
        else:
            verdict=RetentionVerdict.PASS if regression<=package.epsilon_i else RetentionVerdict.REGRESSION
            reasons=("regression_within_epsilon",) if verdict is RetentionVerdict.PASS else ("regression_exceeds_epsilon",)
        decision=RetentionDecisionReceipt(decision_id,"genesis.m4",package.package_hash,baseline.receipt_hash,observation.observation_hash,state.state_hash,view.view_hash,baseline.score,observation.observed_score,regression,package.epsilon_i,verdict,tuple(reasons),tuple(surface_hashes),request.request_hash if request else None)
        return RetentionEvaluation(decision,request)
