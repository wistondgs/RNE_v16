"""Append-only provenance-risk assessments, deliberately separate from trust."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import is_artifact_hash
from lab.genesis.provenance.edges import EdgeClass
from lab.genesis.provenance.graph import ProvenanceGraph


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """An evidence-risk score, not a probability of falsity."""

    assessment_id: str
    target_node_id: str
    schema_version: str
    risk_score: float
    reason_codes: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    producer: str
    previous_assessment_hash: str | None = None
    assessment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.risk_score <= 1.0:
            raise ValueError("genesis_risk_score_out_of_range")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "evidence_hashes", tuple(self.evidence_hashes))
        if any(not is_artifact_hash(item) for item in self.evidence_hashes):
            raise ValueError("genesis_risk_evidence_hash_invalid")
        object.__setattr__(self, "assessment_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "assessment_id": self.assessment_id,
            "target_node_id": self.target_node_id,
            "schema_version": self.schema_version,
            "risk_score": self.risk_score,
            "reason_codes": self.reason_codes,
            "evidence_hashes": self.evidence_hashes,
            "producer": self.producer,
            "previous_assessment_hash": self.previous_assessment_hash,
        }


class RiskAssessmentLedger:
    """Per-target append-only chain; lower later scores never erase prior risk."""

    def __init__(self) -> None:
        self._assessments: tuple[RiskAssessment, ...] = ()

    @property
    def assessments(self) -> tuple[RiskAssessment, ...]:
        return self._assessments

    def append(self, assessment: RiskAssessment) -> bool:
        if assessment.assessment_hash != canonical_sha256(assessment.canonical_payload()):
            raise ValueError("genesis_risk_assessment_hash_invalid")
        for previous in self._assessments:
            if previous.assessment_hash == assessment.assessment_hash:
                if previous.canonical_payload() == assessment.canonical_payload():
                    return False
                raise ValueError("genesis_risk_conflicting_duplicate")
        latest = next(
            (item for item in reversed(self._assessments) if item.target_node_id == assessment.target_node_id),
            None,
        )
        if assessment.previous_assessment_hash != (latest.assessment_hash if latest else None):
            raise ValueError("genesis_risk_previous_chain_invalid")
        self._assessments = (*self._assessments, assessment)
        return True


class ProvenanceRiskPolicy:
    """Compute bounded max-lineage risk; it intentionally has no lowering rule."""

    def assess(
        self, graph: ProvenanceGraph, assessments: Iterable[RiskAssessment]
    ) -> dict[str, float]:
        if graph.verify():
            raise ValueError("genesis_risk_graph_invalid")
        direct = {node.node_id: 0.0 for node in graph.nodes}
        for assessment in assessments:
            if assessment.assessment_hash != canonical_sha256(assessment.canonical_payload()):
                raise ValueError("genesis_risk_assessment_hash_invalid")
            if assessment.target_node_id not in direct:
                raise ValueError("genesis_risk_target_missing")
            # Max over history means a later benign assessment cannot silently
            # erase the provenance burden recorded earlier.
            direct[assessment.target_node_id] = max(
                direct[assessment.target_node_id], assessment.risk_score
            )
        lineage = [edge for edge in graph.edges if edge.edge_class is EdgeClass.LINEAGE]
        indegree = {node.node_id: 0 for node in graph.nodes}
        for edge in lineage:
            indegree[edge.target_node_id] += 1
        ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for edge in sorted(
                (item for item in lineage if item.source_node_id == current),
                key=lambda item: (item.target_node_id, item.edge_hash),
            ):
                indegree[edge.target_node_id] -= 1
                if indegree[edge.target_node_id] == 0:
                    ready.append(edge.target_node_id)
                    ready.sort()
        if len(ordered) != len(indegree):
            raise ValueError("genesis_risk_lineage_cycle")
        result = dict(direct)
        for parent in ordered:
            for edge in lineage:
                if edge.source_node_id == parent:
                    result[edge.target_node_id] = max(
                        result[edge.target_node_id], edge.weight * result[parent]
                    )
        return {node_id: result[node_id] for node_id in sorted(result)}
