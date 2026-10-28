"""Deterministic, in-memory materialization of immutable provenance records."""

from __future__ import annotations

from collections import deque

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.provenance.edges import EdgeClass, ProvenanceEdge
from lab.genesis.provenance.nodes import ProvenanceNode


class ProvenanceGraph:
    """A view only: authoritative node/edge history belongs in an EvidenceLedger."""

    def __init__(self) -> None:
        self._nodes: dict[str, ProvenanceNode] = {}
        self._edges: dict[str, ProvenanceEdge] = {}

    @property
    def nodes(self) -> tuple[ProvenanceNode, ...]:
        return tuple(sorted(self._nodes.values(), key=lambda node: (node.node_hash, node.node_id)))

    @property
    def edges(self) -> tuple[ProvenanceEdge, ...]:
        return tuple(sorted(self._edges.values(), key=lambda edge: (edge.edge_hash, edge.edge_id)))

    def add_node(self, node: ProvenanceNode) -> bool:
        existing = self._nodes.get(node.node_id)
        if existing is None:
            self._nodes[node.node_id] = node
            return True
        if existing.canonical_payload() == node.canonical_payload():
            return False
        raise ValueError("genesis_provenance_node_id_conflict")

    def _has_lineage_path(self, start: str, target: str) -> bool:
        pending = deque([start])
        visited: set[str] = set()
        while pending:
            current = pending.popleft()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(
                edge.target_node_id
                for edge in self._edges.values()
                if edge.edge_class is EdgeClass.LINEAGE and edge.source_node_id == current
            )
        return False

    def add_edge(self, edge: ProvenanceEdge) -> bool:
        if edge.source_node_id not in self._nodes or edge.target_node_id not in self._nodes:
            raise ValueError("genesis_provenance_edge_node_missing")
        existing = self._edges.get(edge.edge_id)
        if existing is not None:
            if existing.canonical_payload() == edge.canonical_payload():
                return False
            raise ValueError("genesis_provenance_edge_id_conflict")
        if edge.edge_class is EdgeClass.LINEAGE and self._has_lineage_path(
            edge.target_node_id, edge.source_node_id
        ):
            raise ValueError("genesis_provenance_lineage_cycle")
        self._edges[edge.edge_id] = edge
        return True

    def parents(self, node_id: str, lineage_only: bool = False) -> tuple[ProvenanceNode, ...]:
        edges = (
            edge for edge in self._edges.values()
            if edge.target_node_id == node_id
            and (not lineage_only or edge.edge_class is EdgeClass.LINEAGE)
        )
        return tuple(sorted((self._nodes[edge.source_node_id] for edge in edges), key=lambda node: node.node_id))

    def children(self, node_id: str, lineage_only: bool = False) -> tuple[ProvenanceNode, ...]:
        edges = (
            edge for edge in self._edges.values()
            if edge.source_node_id == node_id
            and (not lineage_only or edge.edge_class is EdgeClass.LINEAGE)
        )
        return tuple(sorted((self._nodes[edge.target_node_id] for edge in edges), key=lambda node: node.node_id))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "nodes": [node.canonical_payload() for node in self.nodes],
            "edges": [edge.canonical_payload() for edge in self.edges],
        }

    @property
    def graph_hash(self) -> str:
        return canonical_sha256(self.canonical_payload())

    def verify(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for node in self._nodes.values():
            if node.node_hash != canonical_sha256(node.canonical_payload()):
                reasons.append(f"node_hash_invalid:{node.node_id}")
        for edge in self._edges.values():
            if edge.edge_hash != canonical_sha256(edge.canonical_payload()):
                reasons.append(f"edge_hash_invalid:{edge.edge_id}")
            if edge.source_node_id not in self._nodes or edge.target_node_id not in self._nodes:
                reasons.append(f"edge_reference_invalid:{edge.edge_id}")
        # Re-run acyclicity against a fresh graph so forced tampering is found.
        checked = ProvenanceGraph()
        try:
            for node in self.nodes:
                checked.add_node(node)
            for edge in self.edges:
                checked.add_edge(edge)
        except ValueError as error:
            reasons.append(str(error))
        return tuple(reasons)
