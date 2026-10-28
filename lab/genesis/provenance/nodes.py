"""Immutable, content-addressed provenance nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import is_artifact_hash


class NodeType(str, Enum):
    EVIDENCE = "EVIDENCE"
    DATASET = "DATASET"
    AUDIT_DATASET = "AUDIT_DATASET"
    HYPOTHESIS = "HYPOTHESIS"
    SKILL = "SKILL"
    CAPABILITY = "CAPABILITY"
    REPRESENTATION = "REPRESENTATION"
    VERIFIER_RECEIPT = "VERIFIER_RECEIPT"
    TRAINING_PATCH = "TRAINING_PATCH"


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    node_id: str
    schema_version: str
    node_type: NodeType
    artifact_hash: str
    producer: str
    metadata_hash: str
    node_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_type", NodeType(self.node_type))
        if not is_artifact_hash(self.artifact_hash) or not is_artifact_hash(self.metadata_hash):
            raise ValueError("genesis_provenance_artifact_hash_invalid")
        object.__setattr__(self, "node_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "schema_version": self.schema_version,
            "node_type": self.node_type.value,
            "artifact_hash": self.artifact_hash,
            "producer": self.producer,
            "metadata_hash": self.metadata_hash,
        }
