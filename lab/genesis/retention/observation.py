"""Observed retention measurements; payloads remain external artifacts."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Mapping
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash

@dataclass(frozen=True, slots=True)
class RetentionObservationReceipt:
    receipt_id: str; schema_version: str; package_hash: str; capability_id: str; audit_dataset_hash: str; verifier_spec_hash: str; metric_spec_hash: str; sampling_policy_hash: str; observed_score: float; sample_count: int; verifier_receipt_hash: str | None; evidence_hashes: tuple[str,...]; auxiliary_metrics: Mapping[str, Any] = field(default_factory=dict); observation_hash: str = field(init=False)
    def __post_init__(self)->None:
        if not math.isfinite(self.observed_score) or self.sample_count<0: raise ValueError("genesis_observation_invalid")
        object.__setattr__(self,"evidence_hashes",tuple(self.evidence_hashes)); object.__setattr__(self,"auxiliary_metrics",freeze(self.auxiliary_metrics)); hashes=(self.package_hash,self.audit_dataset_hash,self.verifier_spec_hash,self.metric_spec_hash,self.sampling_policy_hash,*self.evidence_hashes); hashes += ((self.verifier_receipt_hash,) if self.verifier_receipt_hash else ())
        if any(not is_artifact_hash(value) for value in hashes): raise ValueError("genesis_observation_hash_invalid")
        object.__setattr__(self,"observation_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]: return {"receipt_id":self.receipt_id,"schema_version":self.schema_version,"package_hash":self.package_hash,"capability_id":self.capability_id,"audit_dataset_hash":self.audit_dataset_hash,"verifier_spec_hash":self.verifier_spec_hash,"metric_spec_hash":self.metric_spec_hash,"sampling_policy_hash":self.sampling_policy_hash,"observed_score":self.observed_score,"sample_count":self.sample_count,"verifier_receipt_hash":self.verifier_receipt_hash,"evidence_hashes":self.evidence_hashes,"auxiliary_metrics":self.auxiliary_metrics}
