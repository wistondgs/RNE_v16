from __future__ import annotations

from dataclasses import replace
from math import inf, nan

import pytest

from lab.genesis.causal.snapshot import REQUIRED_SURFACES, CausalSnapshot, CausalSurface, SurfaceState
from lab.genesis.contracts.claims import ChangeClass, ClaimType, TypedClaim
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256
from lab.genesis.contracts.verification import VerificationObligation, VerificationPlan
from lab.genesis.evidence.events import EvidenceEvent
from lab.genesis.replay.verifier import ReplayAttestation, ReplayStatus
from lab.genesis.verifiers.exact import ExactVerifier


def _claim(*, claim_id: str = "claim-increment") -> TypedClaim:
    return TypedClaim(claim_id=claim_id, schema_version="genesis-claim-v1", claim_type=ClaimType.EXACT_FUNCTION, properties={"relation": "output_eq_input_plus", "delta": 1}, assumptions=("candidate_is_safe_callable",), domain={"kind": "integer_range", "min": -10, "max": 10}, budget={"max_evaluations": 21}, falsifiers=("counterexample",), obligations=("exact-domain",), risk_class="low", change_class=ChangeClass.NOT_APPLICABLE)


def _plan(claim: TypedClaim) -> VerificationPlan:
    obligation = VerificationObligation("exact-domain", "EXHAUSTIVE", "candidate", "experimental", ("genesis.exact_function",), "FAIL")
    return VerificationPlan("plan-increment", claim.claim_hash, (obligation,), {"max_evaluations": 21}, {"genesis.exact_function": "v1"})


def _snapshot(claim: TypedClaim, *, cache_state: SurfaceState = SurfaceState.CAPTURED) -> CausalSnapshot:
    return CausalSnapshot("snapshot-increment", "genesis-causal-snapshot-v0", claim.claim_hash, tuple(CausalSurface(name, cache_state if name == "cache" else SurfaceState.CAPTURED) for name in REQUIRED_SURFACES), {"claim": claim.claim_hash})


def _artifacts():
    claim = _claim()
    plan = _plan(claim)
    snapshot = _snapshot(claim)
    receipt = ExactVerifier().verify(claim, lambda value: value + 1, {"plan_hash": plan.plan_hash, "snapshot_hash": snapshot.snapshot_hash})
    first = EvidenceEvent("event-0", "genesis-evidence-event-v1", claim.claim_id, "VERIFICATION", receipt.receipt_hash, receipt.receipt_hash, None, 0, "genesis.test")
    second = EvidenceEvent("event-1", "genesis-evidence-event-v1", claim.claim_id, "REPLAY_READY", snapshot.snapshot_hash, receipt.receipt_hash, first.event_hash, 1, "genesis.test")
    return claim, plan, snapshot, receipt, (first, second)


def test_claim_snapshot_receipt_event_reload_and_replay():
    claim, plan, snapshot, receipt, events = _artifacts()
    assert receipt.status.value == "PASS"
    assert receipt.coverage == {"checked": 21, "total": 21}
    # Canonical bytes are the process-independent reload representation.
    assert canonical_json_bytes(claim.canonical_payload()) == canonical_json_bytes(claim.canonical_payload())
    assert ReplayAttestation.verify(claim, plan, snapshot, receipt, events).status is ReplayStatus.PASS


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_serialization_rejects_nonfinite_values(value):
    with pytest.raises(ValueError, match="nonfinite"):
        canonical_json_bytes({"bad": value})


def test_unknown_material_surface_cannot_certify_cfi():
    claim = _claim()
    snapshot = _snapshot(claim, cache_state=SurfaceState.UNKNOWN)
    assert snapshot.is_cfi_certifiable() is False


def test_learning_rule_patch_rejects_run_side_and_accepts_learning_rule():
    values = dict(_claim().canonical_payload())
    values.update(claim_id="learning-rule", claim_type=ClaimType.LEARNING_RULE_PATCH, change_class=ChangeClass.RUN_SIDE)
    with pytest.raises(ValueError, match="learning_rule"):
        TypedClaim(**values)
    values["change_class"] = ChangeClass.LEARNING_RULE
    assert TypedClaim(**values).change_class is ChangeClass.LEARNING_RULE


def test_tamper_of_every_critical_artifact_fails_replay_or_changes_hash():
    claim, plan, snapshot, receipt, events = _artifacts()
    assert _claim(claim_id="tampered").claim_hash != claim.claim_hash
    assert replace(plan, plan_id="tampered").plan_hash != plan.plan_hash
    assert replace(snapshot, snapshot_id="tampered").snapshot_hash != snapshot.snapshot_hash
    assert replace(receipt, verifier_version="v2").receipt_hash != receipt.receipt_hash
    assert replace(receipt, evidence={"tampered": True}).receipt_hash != receipt.receipt_hash
    bad_parent = replace(events[1], parent_hash="not-parent")
    assert ReplayAttestation.verify(claim, plan, snapshot, receipt, (events[0], bad_parent)).status is ReplayStatus.FAIL
    bad_evidence = replace(events[0], artifact_hash="unreferenced")
    assert ReplayAttestation.verify(claim, plan, snapshot, receipt, (bad_evidence,)).status is ReplayStatus.FAIL
    assert canonical_sha256(receipt.canonical_payload()) == receipt.receipt_hash
