"""M6C temporal binding: G1 admits its frozen G0 and CFI evidence by closure."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from lab.genesis.causal.cfi import CFIReport, CFIStatus
from lab.genesis.causal.fork import RootSnapshot
from lab.genesis.causal.snapshot import CausalSnapshot, CausalSurface
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.trace_persistence import PersistedTrace, replay_m6_trace, persist_m6_trace
from lab.genesis.intervention.effects import CausalEffectSummary
from lab.genesis.intervention.kernel import KernelResult
from lab.genesis.intervention.receipts import (ArmExecutionReceipt, BudgetReceipt, DecisionSeal,
                                                ExecutionTrace, OracleReceipt)
from lab.genesis.intervention.replay import CausalExperimentReplay
from lab.genesis.intervention.specs import ArmSpec, CausalExperimentManifest
from lab.genesis.causal.isolation import AllowedDeltaReceipt, ArmIsolationReceipt


@dataclass(frozen=True, slots=True)
class TemporalLoop:
    baseline_closure_hash: str
    successor_closure_hash: str
    cfi_report_hash: str
    temporal_hash: str


def _payloads(result: KernelResult) -> dict[str, tuple[Any, ...]]:
    return {
        "m6c_m5_root_snapshot": (result.root,),
        "m6c_m5_manifest": (result.manifest,),
        "m6c_m5_cfi_report": (result.cfi,),
        "m6c_m5_summary": (result.summary,),
        "m6c_m5_execution_trace": (result.trace,),
        "m6c_m5_arm_receipt": result.receipts,
        "m6c_m5_delta_receipt": result.delta_receipts,
        "m6c_m5_isolation_receipt": result.isolation_receipts,
        "m6c_m5_decision_seal": result.seals,
        "m6c_m5_oracle_receipt": result.oracles,
        "m6c_m5_budget_receipt": result.budgets,
    }


def _claim_hash(store: ContentAddressedArtifactStore, closure_hash: str) -> str:
    closure = store.get(closure_hash)
    group = next(item for item in closure["artifact_groups"] if item["role"] == "federation_plan")
    return store.get(group["artifact_hashes"][0])["claim_hash"]


def persist_temporal_loop(store: ContentAddressedArtifactStore, *, baseline_snapshot: CausalSnapshot,
                          baseline_trace: Mapping[str, Any], successor_snapshot: CausalSnapshot,
                          successor_trace: Mapping[str, Any], intervention: KernelResult) -> TemporalLoop:
    """Persist G0 first, then make G1's closure the durable temporal root."""
    if CausalExperimentReplay.verify(intervention).status != "PASS":
        raise ValueError("genesis_temporal_m5_replay_invalid")
    if intervention.cfi.status is not CFIStatus.PASS or not intervention.summary.attribution_eligible:
        raise ValueError("genesis_temporal_cfi_not_confirmatory")
    claim_hash = baseline_trace["router"].claim.claim_hash
    if (successor_trace["router"].claim.claim_hash != claim_hash
            or baseline_snapshot.claim_hash != claim_hash
            or successor_snapshot.claim_hash != claim_hash
            or intervention.manifest.claim_hash != claim_hash):
        raise ValueError("genesis_temporal_claim_binding_invalid")
    baseline = persist_m6_trace(
        store, **baseline_trace,
        historical_artifacts={"m6c_causal_snapshot": (baseline_snapshot,)},
    )
    extras = _payloads(intervention) | {
        "m6c_causal_snapshot": (successor_snapshot,),
        "m6c_baseline_closure": (store.get(baseline.closure_hash),),
    }
    successor = persist_m6_trace(store, **successor_trace, historical_artifacts=extras)
    temporal_hash = canonical_sha256({
        "baseline_closure_hash": baseline.closure_hash,
        "successor_closure_hash": successor.closure_hash,
        "cfi_report_hash": intervention.cfi.report_hash,
    })
    return TemporalLoop(baseline.closure_hash, successor.closure_hash, intervention.cfi.report_hash, temporal_hash)


def _group(store: ContentAddressedArtifactStore, closure: Mapping[str, Any], role: str) -> tuple[Mapping[str, Any], ...]:
    item = next((entry for entry in closure["artifact_groups"] if entry["role"] == role), None)
    if item is None:
        raise ValueError(f"genesis_temporal_role_missing:{role}")
    return tuple(store.get(value) for value in item["artifact_hashes"])


def replay_temporal_loop(store: ContentAddressedArtifactStore, successor_closure_hash: str) -> tuple[bool, tuple[str, ...]]:
    successor = replay_m6_trace(store, successor_closure_hash)
    if not successor.admitted:
        return False, tuple(f"successor:{item}" for item in successor.reasons)
    try:
        closure = store.get(successor_closure_hash)
        baseline_hash = canonical_sha256(_group(store, closure, "m6c_baseline_closure")[0])
        baseline = replay_m6_trace(store, baseline_hash)
        if not baseline.admitted:
            return False, tuple(f"baseline:{item}" for item in baseline.reasons)
        snapshots = _group(store, closure, "m6c_causal_snapshot")
        successor_snapshot = CausalSnapshot(
            **{**snapshots[0], "surfaces": tuple(CausalSurface(**item) for item in snapshots[0]["surfaces"])}
        )
        baseline_closure = store.get(baseline_hash)
        baseline_snapshot_payload = _group(store, baseline_closure, "m6c_causal_snapshot")[0]
        baseline_snapshot = CausalSnapshot(
            **{**baseline_snapshot_payload, "surfaces": tuple(CausalSurface(**item) for item in baseline_snapshot_payload["surfaces"])}
        )
        if not baseline_snapshot.is_cfi_certifiable() or not successor_snapshot.is_cfi_certifiable():
            return False, ("snapshot_not_cfi_certifiable",)
        if len({baseline_snapshot.claim_hash, successor_snapshot.claim_hash, _claim_hash(store, baseline_hash), _claim_hash(store, successor_closure_hash)}) != 1:
            return False, ("snapshot_trace_claim_mismatch",)
        manifest_payload = _group(store, closure, "m6c_m5_manifest")[0]
        manifest = CausalExperimentManifest(**{**manifest_payload, "arm_specs": tuple(ArmSpec(**item) for item in manifest_payload["arm_specs"])})
        if manifest.claim_hash != successor_snapshot.claim_hash:
            return False, ("m5_claim_mismatch",)
        root = RootSnapshot(**_group(store, closure, "m6c_m5_root_snapshot")[0])
        cfi = CFIReport(**_group(store, closure, "m6c_m5_cfi_report")[0])
        summary = CausalEffectSummary(**_group(store, closure, "m6c_m5_summary")[0])
        trace = ExecutionTrace(**_group(store, closure, "m6c_m5_execution_trace")[0])
        result = KernelResult(
            root, manifest,
            tuple(ArmExecutionReceipt(**item) for item in _group(store, closure, "m6c_m5_arm_receipt")),
            cfi, summary, trace,
            tuple(AllowedDeltaReceipt(**item) for item in _group(store, closure, "m6c_m5_delta_receipt")),
            tuple(ArmIsolationReceipt(**item) for item in _group(store, closure, "m6c_m5_isolation_receipt")),
            tuple(DecisionSeal(**item) for item in _group(store, closure, "m6c_m5_decision_seal")),
            tuple(OracleReceipt(**item) for item in _group(store, closure, "m6c_m5_oracle_receipt")),
            tuple(BudgetReceipt(**item) for item in _group(store, closure, "m6c_m5_budget_receipt")),
        )
        if (CausalExperimentReplay.verify(result).status != "PASS"
                or result.cfi.status is not CFIStatus.PASS
                or not result.summary.attribution_eligible):
            return False, ("m5_cfi_replay_invalid",)
    except (KeyError, TypeError, ValueError, StopIteration):
        return False, ("temporal_historical_material_invalid",)
    return True, ()
