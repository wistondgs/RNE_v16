"""M6B4-B2: fresh-process recovery, fault injection and durable tampering."""
import runpy

import pytest

from lab.genesis.evidence import ContentAddressedArtifactStore, persist_m6_trace, replay_m6_trace, stage_m6_trace


support = runpy.run_path("tests/genesis/test_m6b4_trace_persistence.py")


def test_fresh_process_replay_reconstructs_semantics_and_provenance(tmp_path):
    material = support["valid_trace_material"]()
    staged = stage_m6_trace(**material)
    persisted = persist_m6_trace(ContentAddressedArtifactStore(tmp_path), **material)
    replay = replay_m6_trace(ContentAddressedArtifactStore(tmp_path), persisted.closure_hash)
    assert replay.admitted and replay.adjudication == material["adjudication"]
    assert replay.graph is not None and replay.graph.graph_hash == staged.graph.graph_hash


@pytest.mark.parametrize("fail_on_kind", ("first_artifact", "event_prefix", "seal", "closure"))
def test_preclosure_faults_leave_orphans_not_admission_and_retry_converges(tmp_path, fail_on_kind):
    material = support["valid_trace_material"]()
    staged = stage_m6_trace(**material)
    positions = {
        "first_artifact": 1,
        "event_prefix": len(staged.artifact_commit_order) + 1,
        "seal": len(staged.artifact_commit_order) + len(staged.events) + 1,
        "closure": len(staged.artifact_commit_order) + len(staged.events) + 2,
    }
    failing = support["CountingStore"](tmp_path, fail_on=positions[fail_on_kind])
    with pytest.raises(OSError, match="injected"):
        persist_m6_trace(failing, **material)
    recovered_store = ContentAddressedArtifactStore(tmp_path)
    assert not recovered_store.exists(staged.closure.closure_hash)
    retried = persist_m6_trace(recovered_store, **material)
    assert retried.closure_hash == staged.closure.closure_hash
    assert replay_m6_trace(ContentAddressedArtifactStore(tmp_path), retried.closure_hash).admitted


@pytest.mark.parametrize("target", (
    "federation_plan", "verifier_dependency_graph", "reliability_profile",
    "planned_execution_request", "verifier_receipt", "verifier_execution_record",
    "requirement_evidence_bundle", "requirement_adjudication_receipt",
    "event", "seal", "provenance_node", "provenance_edge", "closure",
))
def test_tampering_any_durable_trace_layer_fails_closed(tmp_path, target):
    material = support["valid_trace_material"]()
    persisted = persist_m6_trace(ContentAddressedArtifactStore(tmp_path), **material)
    closure = persisted.closure
    if target == "event":
        artifact_hash = closure.ordered_ledger_event_hashes[0]
    elif target == "seal":
        artifact_hash = closure.ledger_seal_artifact_hash
    elif target == "provenance_node":
        artifact_hash = closure.provenance_node_artifact_hashes[0]
    elif target == "provenance_edge":
        artifact_hash = closure.provenance_edge_artifact_hashes[0]
    elif target == "closure":
        artifact_hash = persisted.closure_hash
    else:
        artifact_hash = support["role_hash"](closure, target)
    store = ContentAddressedArtifactStore(tmp_path)
    store._path(artifact_hash).write_bytes(b'{"tampered":true}')
    assert not replay_m6_trace(ContentAddressedArtifactStore(tmp_path), persisted.closure_hash).admitted
