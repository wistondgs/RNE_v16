"""Immutable provenance edges.  LINEAGE direction is parent -> child."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lab.genesis.contracts.serialization import canonical_sha256


class EdgeType(str, Enum):
    DERIVED_FROM = "DERIVED_FROM"
    GENERATED_FROM = "GENERATED_FROM"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTED_BY = "CONTRADICTED_BY"
    TRAINED_ON = "TRAINED_ON"
    TRANSFORMED_FROM = "TRANSFORMED_FROM"
    VERIFIED_BY = "VERIFIED_BY"
    AUDITED_BY = "AUDITED_BY"
    CORROBORATED_BY = "CORROBORATED_BY"


class EdgeClass(str, Enum):
    LINEAGE = "LINEAGE"
    RELATIONAL = "RELATIONAL"


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """``source_node_id`` is the parent and ``target_node_id`` its derivative."""

    edge_id: str
    schema_version: str
    source_node_id: str
    target_node_id: str
    edge_type: EdgeType
    edge_class: EdgeClass
    weight: float
    edge_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_type", EdgeType(self.edge_type))
        object.__setattr__(self, "edge_class", EdgeClass(self.edge_class))
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("genesis_provenance_edge_weight_out_of_range")
        object.__setattr__(self, "edge_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "schema_version": self.schema_version,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "edge_type": self.edge_type.value,
            "edge_class": self.edge_class.value,
            "weight": self.weight,
        }
