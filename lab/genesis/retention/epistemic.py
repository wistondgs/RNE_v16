"""Frozen snapshots of the M3 epistemic state used by a retention decision."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.risk import ProvenanceRiskPolicy, RiskAssessment
from lab.genesis.retention.package import RetentionAuditPackage, RetentionSurface
from lab.genesis.security.quarantine import QuarantineReceipt, QuarantineState

def _quarantine_view_hash(receipts: tuple[QuarantineReceipt,...]) -> str:
    return canonical_sha256({"quarantine_receipts": tuple(item.receipt_hash for item in receipts)})

@dataclass(frozen=True, slots=True)
class EpistemicStateRef:
    provenance_graph_hash: str; risk_ledger_head_hash: str; quarantine_ledger_head_hash: str; corroboration_view_hash: str | None; artifact_ledger_seal_hash: str | None; schema_version: str; state_hash: str = field(init=False)
    def __post_init__(self)->None: object.__setattr__(self,"state_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,object]: return {"provenance_graph_hash":self.provenance_graph_hash,"risk_ledger_head_hash":self.risk_ledger_head_hash,"quarantine_ledger_head_hash":self.quarantine_ledger_head_hash,"corroboration_view_hash":self.corroboration_view_hash,"artifact_ledger_seal_hash":self.artifact_ledger_seal_hash,"schema_version":self.schema_version}
    @classmethod
    def from_records(cls, graph: ProvenanceGraph, assessments: Iterable[RiskAssessment], quarantine_receipts: Iterable[QuarantineReceipt], *, schema_version: str="genesis.m4", corroboration_view_hash: str|None=None, artifact_ledger_seal_hash: str|None=None)->"EpistemicStateRef":
        risks=tuple(assessments); quarantine=tuple(quarantine_receipts)
        return cls(graph.graph_hash, risks[-1].assessment_hash if risks else canonical_sha256({"risk_head":None}), _quarantine_view_hash(quarantine), corroboration_view_hash, artifact_ledger_seal_hash, schema_version)

@dataclass(frozen=True, slots=True)
class RetentionSurfaceAssessment:
    surface: RetentionSurface; artifact_hash: str; provenance_node_id: str; risk_score: float; quarantine_state: QuarantineState; risk_assessment_hash: str; quarantine_receipt_hash: str|None; integrity_pass: bool; assessment_hash: str=field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"surface",RetentionSurface(self.surface)); object.__setattr__(self,"quarantine_state",QuarantineState(self.quarantine_state));
        if not 0<=self.risk_score<=1: raise ValueError("genesis_retention_surface_risk_invalid")
        object.__setattr__(self,"assessment_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,object]: return {"surface":self.surface.value,"artifact_hash":self.artifact_hash,"provenance_node_id":self.provenance_node_id,"risk_score":self.risk_score,"quarantine_state":self.quarantine_state.value,"risk_assessment_hash":self.risk_assessment_hash,"quarantine_receipt_hash":self.quarantine_receipt_hash,"integrity_pass":self.integrity_pass}

@dataclass(frozen=True, slots=True)
class RetentionEpistemicView:
    epistemic_state_hash: str; assessments: tuple[RetentionSurfaceAssessment,...]; view_hash: str=field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"assessments",tuple(sorted(self.assessments,key=lambda item:item.surface.value))); object.__setattr__(self,"view_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,object]: return {"epistemic_state_hash":self.epistemic_state_hash,"assessments":tuple(item.canonical_payload() for item in self.assessments)}
    def for_surface(self,surface:RetentionSurface)->RetentionSurfaceAssessment: return next(item for item in self.assessments if item.surface is surface)
    @classmethod
    def materialize(cls, package: RetentionAuditPackage, state: EpistemicStateRef, store: ContentAddressedArtifactStore, graph: ProvenanceGraph, assessments: Iterable[RiskAssessment], quarantine_receipts: Iterable[QuarantineReceipt])->"RetentionEpistemicView":
        risks=tuple(assessments); quarantines=tuple(quarantine_receipts); scores=ProvenanceRiskPolicy().assess(graph,risks)
        direct: dict[str,RiskAssessment]={}
        for item in risks:
            if item.target_node_id not in direct or (item.risk_score,item.assessment_hash)>(direct[item.target_node_id].risk_score,direct[item.target_node_id].assessment_hash): direct[item.target_node_id]=item
        quarantine_by_target:dict[str,QuarantineReceipt]={}
        for item in quarantines: quarantine_by_target[item.target_hash]=item
        nodes={node.node_id:node for node in graph.nodes}; result=[]
        for surface in package.critical_surfaces():
            node_id=package.provenance_node_ids[surface.value]; node=nodes.get(node_id); artifact=package.artifact_hash_for(surface)
            integrity=bool(node and node.artifact_hash==artifact and store.verify(artifact))
            receipt=quarantine_by_target.get(artifact); risk_source=direct.get(node_id)
            # Inherited risk keeps a pointer to the source assessment where possible.
            if risk_source is None and scores.get(node_id,0):
                for edge in graph.edges:
                    if edge.target_node_id==node_id and scores.get(edge.source_node_id,0)*edge.weight==scores.get(node_id,0): risk_source=direct.get(edge.source_node_id); break
            result.append(RetentionSurfaceAssessment(surface,artifact,node_id,scores.get(node_id,0.0),receipt.new_state if receipt else QuarantineState.NORMAL,risk_source.assessment_hash if risk_source else canonical_sha256({"no_direct_risk":node_id}),receipt.receipt_hash if receipt else None,integrity))
        return cls(state.state_hash,tuple(result))
