from __future__ import annotations

import pytest

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.provenance.edges import EdgeClass, EdgeType, ProvenanceEdge
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType, ProvenanceNode


def node(node_id: str, kind: NodeType = NodeType.EVIDENCE) -> ProvenanceNode:
    return ProvenanceNode(node_id, "m3", kind, canonical_sha256({"payload": node_id}), "test", canonical_sha256({"metadata": node_id}))


def edge(edge_id: str, source: str, target: str, edge_class: EdgeClass = EdgeClass.LINEAGE) -> ProvenanceEdge:
    return ProvenanceEdge(edge_id, "m3", source, target, EdgeType.DERIVED_FROM, edge_class, 0.5)


def test_lineage_cycles_are_rejected_but_relational_cycles_are_allowed():
    graph = ProvenanceGraph()
    for name in ("a", "b", "c"):
        graph.add_node(node(name))
    graph.add_edge(edge("ab", "a", "b"))
    graph.add_edge(edge("bc", "b", "c"))
    with pytest.raises(ValueError, match="lineage_cycle"):
        graph.add_edge(edge("ca", "c", "a"))
    assert graph.add_edge(edge("ca-relation", "c", "a", EdgeClass.RELATIONAL))
    assert [item.node_id for item in graph.parents("b", lineage_only=True)] == ["a"]
    assert [item.node_id for item in graph.children("a", lineage_only=True)] == ["b"]


def test_graph_hash_is_independent_of_node_and_edge_insertion_order():
    nodes = [node("a"), node("b", NodeType.HYPOTHESIS), node("c", NodeType.SKILL)]
    edges = [edge("ab", "a", "b"), edge("bc", "b", "c")]
    first = ProvenanceGraph()
    second = ProvenanceGraph()
    for item in nodes:
        first.add_node(item)
    for item in edges:
        first.add_edge(item)
    for item in reversed(nodes):
        second.add_node(item)
    for item in reversed(edges):
        second.add_edge(item)
    assert first.canonical_payload() == second.canonical_payload()
    assert first.graph_hash == second.graph_hash
