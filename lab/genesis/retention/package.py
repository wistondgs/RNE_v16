"""Immutable definition of a provenance-covered retention audit."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore, is_artifact_hash
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType


class RetentionSurface(str, Enum):
    CERT_DATASET = "CERT_DATASET"
    AUDIT_DATASET = "AUDIT_DATASET"
    BASELINE = "BASELINE"
    VERIFIER = "VERIFIER"
    METRIC = "METRIC"
    SAMPLING = "SAMPLING"
    CFI_POLICY = "CFI_POLICY"
    CAPABILITY = "CAPABILITY"


@dataclass(frozen=True, slots=True)
class RetentionAuditPackage:
    package_id: str
    schema_version: str
    capability_id: str
    capability_artifact_hash: str
    cert_dataset_hash: str
    audit_dataset_hash: str
    baseline_receipt_hash: str
    verifier_spec_hash: str
    metric_spec_hash: str
    sampling_policy_hash: str
    cfi_policy_hash: str | None
    epsilon_i: float
    weight_i: float
    sigma_max: float
    provenance_node_ids: Mapping[str, str]
    package_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.epsilon_i < 0 or self.weight_i < 0 or not 0 <= self.sigma_max <= 1:
            raise ValueError("genesis_retention_package_bounds_invalid")
        hashes = [self.capability_artifact_hash, self.cert_dataset_hash, self.audit_dataset_hash,
                  self.baseline_receipt_hash, self.verifier_spec_hash, self.metric_spec_hash,
                  self.sampling_policy_hash]
        if self.cfi_policy_hash is not None:
            hashes.append(self.cfi_policy_hash)
        if any(not is_artifact_hash(value) for value in hashes):
            raise ValueError("genesis_retention_package_hash_invalid")
        mapping = {str(key.value if isinstance(key, RetentionSurface) else key): str(value)
                   for key, value in self.provenance_node_ids.items()}
        required = {surface.value for surface in self.critical_surfaces()}
        if set(mapping) != required:
            raise ValueError("genesis_retention_package_surface_nodes_invalid")
        object.__setattr__(self, "provenance_node_ids", freeze(mapping))
        object.__setattr__(self, "package_hash", canonical_sha256(self.canonical_payload()))

    def critical_surfaces(self) -> tuple[RetentionSurface, ...]:
        core = (RetentionSurface.CERT_DATASET, RetentionSurface.AUDIT_DATASET,
                RetentionSurface.BASELINE, RetentionSurface.VERIFIER,
                RetentionSurface.METRIC, RetentionSurface.SAMPLING,
                RetentionSurface.CAPABILITY)
        return core + ((RetentionSurface.CFI_POLICY,) if self.cfi_policy_hash else ())

    def artifact_hash_for(self, surface: RetentionSurface) -> str:
        return {
            RetentionSurface.CERT_DATASET: self.cert_dataset_hash,
            RetentionSurface.AUDIT_DATASET: self.audit_dataset_hash,
            RetentionSurface.BASELINE: self.baseline_receipt_hash,
            RetentionSurface.VERIFIER: self.verifier_spec_hash,
            RetentionSurface.METRIC: self.metric_spec_hash,
            RetentionSurface.SAMPLING: self.sampling_policy_hash,
            RetentionSurface.CAPABILITY: self.capability_artifact_hash,
            RetentionSurface.CFI_POLICY: self.cfi_policy_hash,
        }[surface]  # type: ignore[return-value]

    def canonical_payload(self) -> dict[str, object]:
        return {"package_id": self.package_id, "schema_version": self.schema_version,
                "capability_id": self.capability_id, "capability_artifact_hash": self.capability_artifact_hash,
                "cert_dataset_hash": self.cert_dataset_hash, "audit_dataset_hash": self.audit_dataset_hash,
                "baseline_receipt_hash": self.baseline_receipt_hash, "verifier_spec_hash": self.verifier_spec_hash,
                "metric_spec_hash": self.metric_spec_hash, "sampling_policy_hash": self.sampling_policy_hash,
                "cfi_policy_hash": self.cfi_policy_hash, "epsilon_i": self.epsilon_i, "weight_i": self.weight_i,
                "sigma_max": self.sigma_max, "provenance_node_ids": self.provenance_node_ids}

    def validate_bindings(self, store: ContentAddressedArtifactStore, graph: ProvenanceGraph) -> tuple[str, ...]:
        reasons: list[str] = []
        for surface in self.critical_surfaces():
            artifact_hash = self.artifact_hash_for(surface)
            node_id = self.provenance_node_ids.get(surface.value)
            node = next((item for item in graph.nodes if item.node_id == node_id), None)
            if not store.verify(artifact_hash): reasons.append(f"artifact_invalid:{surface.value}")
            if node is None or node.artifact_hash != artifact_hash: reasons.append(f"node_binding_invalid:{surface.value}")
            elif surface is RetentionSurface.AUDIT_DATASET and node.node_type is not NodeType.AUDIT_DATASET:
                reasons.append("audit_dataset_node_type_invalid")
        return tuple(reasons)
