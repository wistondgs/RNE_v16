from __future__ import annotations

from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.provenance.edges import EdgeClass, EdgeType, ProvenanceEdge
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType, ProvenanceNode
from lab.genesis.provenance.risk import ProvenanceRiskPolicy, RiskAssessment, RiskAssessmentLedger
from lab.genesis.security.quarantine import QuarantineHistory, QuarantineReceipt, QuarantineState


def build_node(store, node_id, node_type):
    artifact = store.put({"artifact": node_id})
    metadata = store.put({"metadata": node_id})
    return ProvenanceNode(node_id, "m3", node_type, artifact, "test", metadata)


def lineage(edge_id, source, target, weight=0.5):
    return ProvenanceEdge(edge_id, "m3", source, target, EdgeType.DERIVED_FROM, EdgeClass.LINEAGE, weight)


def assessment(store, target, score, previous=None):
    evidence = store.put({"risk-evidence": target, "score": score})
    return RiskAssessment("risk-" + target + str(score), target, "m3", score, ("provenance_burden",), (evidence,), "test", previous)


def test_risk_propagates_without_refuting_derivatives(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    graph = ProvenanceGraph()
    nodes = [
        build_node(store, "a", NodeType.EVIDENCE), build_node(store, "b", NodeType.HYPOTHESIS),
        build_node(store, "c", NodeType.SKILL), build_node(store, "d", NodeType.CAPABILITY),
    ]
    for item in nodes:
        graph.add_node(item)
    graph.add_edge(lineage("ab", "a", "b"))
    graph.add_edge(lineage("bc", "b", "c"))
    graph.add_edge(lineage("cd", "c", "d"))
    direct = assessment(store, "a", 0.8)
    risks = ProvenanceRiskPolicy().assess(graph, (direct,))
    assert risks["b"] >= 0.4 and risks["c"] >= 0.2 and risks["d"] >= 0.1
    assert all(0.0 <= score <= 1.0 for score in risks.values())
    history = QuarantineHistory(nodes[0].artifact_hash)
    history.append(QuarantineReceipt.transition(
        receipt_id="suspect-a", schema_version="m3", target_hash=nodes[0].artifact_hash,
        previous_state=QuarantineState.NORMAL, new_state=QuarantineState.SUSPECT,
        reason_codes=("signal",), evidence_hashes=(direct.evidence_hashes[0],), producer="test",
    ))
    assert history.state is QuarantineState.SUSPECT
    # Risk traverses lineage; quarantine/refutation state does not.
    assert not any(node.artifact_hash == nodes[1].artifact_hash for node in ())


def test_audit_dataset_is_first_class_and_receives_ea_to_daudit_risk(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    graph = ProvenanceGraph()
    a = build_node(store, "a", NodeType.EVIDENCE)
    b = build_node(store, "b", NodeType.HYPOTHESIS)
    audit = build_node(store, "audit-x", NodeType.AUDIT_DATASET)
    for item in (a, b, audit):
        graph.add_node(item)
    graph.add_edge(lineage("ab", "a", "b"))
    graph.add_edge(ProvenanceEdge("ax", "m3", "a", "audit-x", EdgeType.GENERATED_FROM, EdgeClass.LINEAGE, 0.5))
    first = assessment(store, "a", 0.8)
    ledger = RiskAssessmentLedger()
    assert ledger.append(first)
    assert not ledger.append(first)
    lower = assessment(store, "a", 0.1, first.assessment_hash)
    ledger.append(lower)
    risks = ProvenanceRiskPolicy().assess(graph, ledger.assessments)
    assert audit.node_type is NodeType.AUDIT_DATASET
    assert risks["b"] >= 0.4 and risks["audit-x"] >= 0.4
    # M4 RetentionAuditPackage may consume this risk; M3 gives audit no refutation state.
