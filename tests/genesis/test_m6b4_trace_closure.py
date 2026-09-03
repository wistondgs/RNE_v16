"""M6B4-B0: pure trace-closure identity, transcript and tamper gates."""
from dataclasses import replace

from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence import (
    TRACE_SCHEMA_VERSION, EvidenceEvent, EvidenceLedger, LedgerSeal,
    TraceArtifactGroup, TraceClosureManifest, derive_trace_id,
    verify_trace_closure,
)


def payload(name):
    value = {"artifact": name}
    return canonical_sha256(value), value


def trace_inputs(**changes):
    values = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "federation_plan_hash": payload("plan")[0],
        "requirement_hash": payload("requirement")[0],
        "execution_subject_hash": payload("subject")[0],
        "evidence_bundle_hash": payload("bundle")[0],
        "adjudication_receipt_hash": payload("adjudication")[0],
    } | changes
    return values


def material():
    inputs = trace_inputs()
    trace_id = derive_trace_id(**inputs)
    payloads = {artifact_hash: value for artifact_hash, value in (
        payload("plan"), payload("requirement"), payload("subject"),
        payload("bundle"), payload("adjudication"), payload("descriptor"),
        payload("provenance-node"), payload("provenance-edge"),
        payload("event-artifact-0"), payload("event-artifact-1"),
    )}
    event_artifacts = tuple(sorted(
        value for value in payloads if payloads[value]["artifact"].startswith("event-artifact")
    ))
    ledger = EvidenceLedger(f"genesis-m6b4:{trace_id}", trace_id)
    events = []
    for sequence, artifact_hash in enumerate(event_artifacts):
        event = EvidenceEvent(
            f"m6b4-event-{sequence}", TRACE_SCHEMA_VERSION, trace_id,
            "m6_artifact", artifact_hash, inputs["adjudication_receipt_hash"],
            ledger.head_hash, sequence, "genesis.m6b4",
        )
        ledger.append(event)
        events.append(event)
    seal = LedgerSeal.seal(ledger, TRACE_SCHEMA_VERSION)
    payloads[seal.seal_hash] = seal.canonical_payload()
    groups = (
        TraceArtifactGroup("federation_plan", (inputs["federation_plan_hash"],)),
        TraceArtifactGroup("historical_descriptor", (payload("descriptor")[0],)),
        TraceArtifactGroup("requirement", (inputs["requirement_hash"],)),
    )
    closure = TraceClosureManifest(
        **inputs, trace_id=trace_id, artifact_groups=groups,
        ordered_ledger_event_artifact_hashes=event_artifacts,
        ordered_ledger_event_hashes=tuple(event.event_hash for event in events),
        ledger_head_hash=ledger.head_hash, ledger_event_count=len(events),
        ledger_seal_artifact_hash=seal.seal_hash,
        provenance_node_artifact_hashes=(payload("provenance-node")[0],),
        provenance_edge_artifact_hashes=(payload("provenance-edge")[0],),
    )
    return inputs, payloads, tuple(events), seal, closure


def test_trace_identity_is_deterministic_separated_and_field_order_invariant():
    inputs = trace_inputs()
    assert derive_trace_id(**inputs) == derive_trace_id(**dict(reversed(tuple(inputs.items()))))
    baseline = derive_trace_id(**inputs)
    for field in ("federation_plan_hash", "requirement_hash", "execution_subject_hash",
                  "evidence_bundle_hash", "adjudication_receipt_hash"):
        assert derive_trace_id(**(inputs | {field: payload(f"other-{field}")[0]})) != baseline


def test_closure_is_deterministic_and_verifies_its_complete_transcript():
    _inputs, payloads, events, seal, closure = material()
    assert closure.validate()
    assert not verify_trace_closure(closure, artifact_payloads=payloads, events=events, seal=seal)
    reordered_groups = tuple(reversed(closure.artifact_groups))
    same = replace(closure, artifact_groups=reordered_groups)
    assert same.closure_hash == closure.closure_hash


def test_closure_fails_closed_for_artifact_transcript_and_seal_tampering():
    _inputs, payloads, events, seal, closure = material()
    missing = dict(payloads)
    missing.pop(closure.federation_plan_hash)
    assert any(reason.startswith("artifact_missing") for reason in verify_trace_closure(closure, artifact_payloads=missing, events=events, seal=seal))

    latest = dict(payloads)
    latest[closure.federation_plan_hash] = {"artifact": "latest-substitution"}
    assert any(reason.startswith("artifact_hash_invalid") for reason in verify_trace_closure(closure, artifact_payloads=latest, events=events, seal=seal))

    assert "ledger_event_order_invalid" in verify_trace_closure(closure, artifact_payloads=payloads, events=tuple(reversed(events)), seal=seal)
    object.__setattr__(seal, "head_hash", "0" * 64)
    assert "ledger_seal_hash_invalid" in verify_trace_closure(closure, artifact_payloads=payloads, events=events, seal=seal)


def test_resealed_historical_substitution_is_a_new_root_not_the_original_trace():
    inputs, payloads, events, seal, closure = material()
    replacement_hash, replacement_payload = payload("other-historical-descriptor")
    payloads[replacement_hash] = replacement_payload
    changed = replace(
        closure,
        artifact_groups=(
            TraceArtifactGroup("federation_plan", (inputs["federation_plan_hash"],)),
            TraceArtifactGroup("historical_descriptor", (replacement_hash,)),
            TraceArtifactGroup("requirement", (inputs["requirement_hash"],)),
        ),
    )
    assert changed.validate() and changed.closure_hash != closure.closure_hash
    assert closure.closure_hash != canonical_sha256(changed.canonical_payload())
    assert "closure_root_mismatch" in verify_trace_closure(
        changed, artifact_payloads=payloads, events=events, seal=seal,
        expected_closure_hash=closure.closure_hash,
    )


def test_closure_rejects_wrong_head_count_and_self_ledger_reference():
    _inputs, payloads, events, seal, closure = material()
    object.__setattr__(closure, "ledger_head_hash", "0" * 64)
    assert not closure.validate()

    _inputs, payloads, events, seal, closure = material()
    object.__setattr__(closure, "ledger_event_count", 99)
    assert not closure.validate()

    _inputs, payloads, events, seal, closure = material()
    object.__setattr__(closure, "ordered_ledger_event_artifact_hashes", (closure.closure_hash,))
    assert not closure.validate()
