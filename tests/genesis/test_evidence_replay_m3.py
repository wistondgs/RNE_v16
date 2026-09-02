from __future__ import annotations

import pytest

from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.events import EvidenceEvent
from lab.genesis.evidence.ledger import EvidenceLedger
from lab.genesis.evidence.seals import LedgerSeal
from lab.genesis.provenance.edges import EdgeClass, EdgeType, ProvenanceEdge
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType, ProvenanceNode
from lab.genesis.provenance.risk import RiskAssessment
from lab.genesis.replay.verifier import EvidenceReplay, ReplayStatus
from lab.genesis.security.corroboration import CorroborationReceipt, IndependenceStatus
from lab.genesis.security.quarantine import QuarantineReceipt, QuarantineState


def bundle(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    payload_hash = store.put({"measurement": "e_a"})
    metadata_hash = store.put({"source": "instrument"})
    evidence = ProvenanceNode("a", "m3", NodeType.EVIDENCE, payload_hash, "test", metadata_hash)
    hypothesis_payload = store.put({"hypothesis": "b"})
    hypothesis_metadata = store.put({"source": "analysis"})
    hypothesis = ProvenanceNode("b", "m3", NodeType.HYPOTHESIS, hypothesis_payload, "test", hypothesis_metadata)
    graph = ProvenanceGraph()
    graph.add_node(evidence)
    graph.add_node(hypothesis)
    edge = ProvenanceEdge("ab", "m3", "a", "b", EdgeType.DERIVED_FROM, EdgeClass.LINEAGE, 0.5)
    graph.add_edge(edge)
    node_record = store.put(evidence.canonical_payload())
    edge_record = store.put(edge.canonical_payload())
    ledger = EvidenceLedger("ledger-m3", "subject-m3")
    first = EvidenceEvent("e0", "m3", "subject-m3", "artifact", payload_hash, "b" * 64, None, 0, "test")
    second = EvidenceEvent("e1", "m3", "subject-m3", "provenance_node", node_record, "b" * 64, first.event_hash, 1, "test")
    third = EvidenceEvent("e2", "m3", "subject-m3", "provenance_edge", edge_record, "b" * 64, second.event_hash, 2, "test")
    for event in (first, second, third):
        ledger.append(event)
    seal = LedgerSeal.seal(ledger)
    risk_evidence = store.put({"basis": "source risk"})
    risk = RiskAssessment("r1", "a", "m3", 0.8, ("source_signal",), (risk_evidence,), "test")
    quarantine = QuarantineReceipt.transition(
        receipt_id="q1", schema_version="m3", target_hash=payload_hash,
        previous_state=QuarantineState.NORMAL, new_state=QuarantineState.SUSPECT,
        reason_codes=("source_signal",), evidence_hashes=(risk_evidence,), producer="test",
    )
    corroboration = CorroborationReceipt(
        "c1", "m3", payload_hash, (risk_evidence,), ("producer-2",), ("source-2",),
        IndependenceStatus.CLAIMED, "supports",
    )
    return {
        "store": store, "ledger": ledger, "seal": seal, "graph": graph,
        "risk": risk, "quarantine": quarantine, "corroboration": corroboration,
    }


def replay(data, events=None):
    return EvidenceReplay.verify(
        data["store"], data["ledger"], data["seal"], data["graph"], (data["risk"],),
        (data["quarantine"],), (data["corroboration"],), events=events,
    )


def test_integrated_payload_to_ledger_seal_and_replay(tmp_path):
    data = bundle(tmp_path)
    attestation = replay(data)
    assert attestation.status is ReplayStatus.PASS, attestation.reasons


@pytest.mark.parametrize(
    "tamper",
    (
        "artifact_mutation", "event_mutation", "event_deletion", "event_insertion",
        "event_reorder", "wrong_sequence", "wrong_parent", "seal_head", "seal_count",
        "node_mutation", "edge_mutation", "lineage_cycle", "risk_mutation",
        "quarantine_mutation", "corroboration_mutation",
    ),
)
def test_m3_tamper_matrix_fails_closed(tmp_path, tamper):
    data = bundle(tmp_path)
    observed = None
    events = data["ledger"].events
    if tamper == "artifact_mutation":
        data["store"]._path(events[0].artifact_hash).write_bytes(b"corrupt")
    elif tamper == "event_mutation":
        object.__setattr__(events[0], "producer", "tampered")
    elif tamper == "event_deletion":
        observed = events[:-1]
    elif tamper == "event_insertion":
        inserted = EvidenceEvent("insert", "m3", "subject-m3", "artifact", events[0].artifact_hash, "b" * 64, events[0].event_hash, 1, "test")
        observed = (events[0], inserted, *events[1:])
    elif tamper == "event_reorder":
        observed = (events[1], events[0], events[2])
    elif tamper == "wrong_sequence":
        observed = (EvidenceEvent("bad-seq", "m3", "subject-m3", "artifact", events[0].artifact_hash, "b" * 64, None, 7, "test"), *events[1:])
    elif tamper == "wrong_parent":
        observed = (events[0], EvidenceEvent("bad-parent", "m3", "subject-m3", "artifact", events[1].artifact_hash, "b" * 64, "0" * 64, 1, "test"), events[2])
    elif tamper == "seal_head":
        object.__setattr__(data["seal"], "head_hash", "0" * 64)
    elif tamper == "seal_count":
        object.__setattr__(data["seal"], "event_count", 99)
    elif tamper == "node_mutation":
        object.__setattr__(data["graph"]._nodes["a"], "producer", "tampered")
    elif tamper == "edge_mutation":
        object.__setattr__(data["graph"]._edges["ab"], "weight", 0.1)
    elif tamper == "lineage_cycle":
        data["graph"]._edges["ba"] = ProvenanceEdge("ba", "m3", "b", "a", EdgeType.DERIVED_FROM, EdgeClass.LINEAGE, 0.5)
    elif tamper == "risk_mutation":
        object.__setattr__(data["risk"], "risk_score", 0.1)
    elif tamper == "quarantine_mutation":
        object.__setattr__(data["quarantine"], "producer", "tampered")
    elif tamper == "corroboration_mutation":
        object.__setattr__(data["corroboration"], "verdict", "tampered")
    assert replay(data, observed).status is ReplayStatus.FAIL
