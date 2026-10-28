"""Immutable baseline, decision and reverification receipts for rule A*."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash
from lab.genesis.retention.package import RetentionSurface


def _valid_hashes(values: tuple[str, ...]) -> None:
    if any(not is_artifact_hash(value) for value in values): raise ValueError("genesis_retention_receipt_hash_invalid")

@dataclass(frozen=True, slots=True)
class BaselineMeasurementReceipt:
    receipt_id: str; schema_version: str; capability_id: str; audit_dataset_hash: str; verifier_spec_hash: str; metric_spec_hash: str; sampling_policy_hash: str; score: float; sample_count: int; evidence_hashes: tuple[str, ...]; receipt_hash: str = field(init=False)
    def __post_init__(self) -> None:
        if not math.isfinite(self.score) or self.sample_count < 0: raise ValueError("genesis_baseline_measurement_invalid")
        object.__setattr__(self, "evidence_hashes", tuple(self.evidence_hashes)); _valid_hashes((self.audit_dataset_hash, self.verifier_spec_hash, self.metric_spec_hash, self.sampling_policy_hash, *self.evidence_hashes)); object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))
    def canonical_payload(self) -> dict[str, Any]: return {"receipt_id":self.receipt_id,"schema_version":self.schema_version,"capability_id":self.capability_id,"audit_dataset_hash":self.audit_dataset_hash,"verifier_spec_hash":self.verifier_spec_hash,"metric_spec_hash":self.metric_spec_hash,"sampling_policy_hash":self.sampling_policy_hash,"score":self.score,"sample_count":self.sample_count,"evidence_hashes":self.evidence_hashes}

class RetentionVerdict(str, Enum): PASS="PASS"; REGRESSION="REGRESSION"; INCONCLUSIVE="INCONCLUSIVE"; ERROR="ERROR"

@dataclass(frozen=True, slots=True)
class RetentionReverificationRequest:
    request_id: str; schema_version: str; package_hash: str; trigger_surface: RetentionSurface; trigger_risk_score: float; trigger_quarantine_state: str; reason_codes: tuple[str, ...]; required_checks: tuple[str, ...]; epistemic_state_hash: str; request_hash: str = field(init=False)
    def __post_init__(self) -> None:
        object.__setattr__(self,"trigger_surface",RetentionSurface(self.trigger_surface)); object.__setattr__(self,"reason_codes",tuple(self.reason_codes)); object.__setattr__(self,"required_checks",tuple(self.required_checks));
        if not 0<=self.trigger_risk_score<=1: raise ValueError("genesis_reverification_risk_invalid")
        _valid_hashes((self.package_hash,self.epistemic_state_hash)); object.__setattr__(self,"request_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]: return {"request_id":self.request_id,"schema_version":self.schema_version,"package_hash":self.package_hash,"trigger_surface":self.trigger_surface.value,"trigger_risk_score":self.trigger_risk_score,"trigger_quarantine_state":self.trigger_quarantine_state,"reason_codes":self.reason_codes,"required_checks":self.required_checks,"epistemic_state_hash":self.epistemic_state_hash}

@dataclass(frozen=True, slots=True)
class RetentionDecisionReceipt:
    decision_id: str; schema_version: str; package_hash: str; baseline_receipt_hash: str; observation_receipt_hash: str; epistemic_state_hash: str; epistemic_view_hash: str; baseline_score: float; observed_score: float; regression_value: float; epsilon_i: float; verdict: RetentionVerdict; reason_codes: tuple[str, ...]; critical_surface_assessment_hashes: tuple[str, ...]; reverification_request_hash: str | None = None; decision_hash: str = field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"verdict",RetentionVerdict(self.verdict)); object.__setattr__(self,"reason_codes",tuple(self.reason_codes)); object.__setattr__(self,"critical_surface_assessment_hashes",tuple(self.critical_surface_assessment_hashes));
        if any(not math.isfinite(v) for v in (self.baseline_score,self.observed_score,self.regression_value,self.epsilon_i)) or self.regression_value<0 or self.epsilon_i<0: raise ValueError("genesis_retention_decision_values_invalid")
        hashes=(self.package_hash,self.baseline_receipt_hash,self.observation_receipt_hash,self.epistemic_state_hash,self.epistemic_view_hash,*self.critical_surface_assessment_hashes); _valid_hashes(hashes + ((self.reverification_request_hash,) if self.reverification_request_hash else ())); object.__setattr__(self,"decision_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]: return {"decision_id":self.decision_id,"schema_version":self.schema_version,"package_hash":self.package_hash,"baseline_receipt_hash":self.baseline_receipt_hash,"observation_receipt_hash":self.observation_receipt_hash,"epistemic_state_hash":self.epistemic_state_hash,"epistemic_view_hash":self.epistemic_view_hash,"baseline_score":self.baseline_score,"observed_score":self.observed_score,"regression_value":self.regression_value,"epsilon_i":self.epsilon_i,"verdict":self.verdict.value,"reason_codes":self.reason_codes,"critical_surface_assessment_hashes":self.critical_surface_assessment_hashes,"reverification_request_hash":self.reverification_request_hash}
