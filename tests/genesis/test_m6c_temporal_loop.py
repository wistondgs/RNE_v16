"""M6C: frozen G0/G1 snapshots, CFI and fresh closure replay."""
import runpy

import pytest

from lab.genesis.causal.snapshot import CausalSnapshot, CausalSurface, REQUIRED_SURFACES, SurfaceState
from lab.genesis.evidence import ContentAddressedArtifactStore
from lab.genesis.intervention.kernel import GenericInterventionKernel
from lab.genesis.intervention.specs import CausalExperimentManifest
from lab.genesis.temporal import persist_temporal_loop, replay_temporal_loop


m6 = runpy.run_path("tests/genesis/test_m6b4_trace_persistence.py")
m5 = runpy.run_path("tests/genesis/_m5_helpers.py")


def snapshot(claim_hash, name):
    return CausalSnapshot(
        name, "genesis-m6c-v1", claim_hash,
        tuple(CausalSurface(surface, SurfaceState.CAPTURED, {"digest": f"{name}:{surface}"}) for surface in REQUIRED_SURFACES),
        {"temporal": name},
    )


def cfi_pass_result(claim_hash):
    adapter, root, specs, budget, manifest, oracle = m5["experiment"]()
    manifest = CausalExperimentManifest(
        manifest.experiment_id, manifest.schema_version, claim_hash, manifest.root_snapshot_hash,
        manifest.cfi_policy_hash, manifest.arm_specs, manifest.budget_spec_hash,
        manifest.rng_policy, manifest.master_seed, manifest.oracle_spec_hash,
        manifest.evaluator_version, manifest.required_surfaces,
    )
    return GenericInterventionKernel().run(manifest, root, specs, budget, adapter, oracle)


def test_temporal_loop_replays_g0_g1_and_cfi_from_successor_closure(tmp_path):
    baseline = m6["valid_trace_material"]()
    successor = m6["valid_trace_material"]()
    claim_hash = baseline["router"].claim.claim_hash
    result = cfi_pass_result(claim_hash)
    loop = persist_temporal_loop(
        ContentAddressedArtifactStore(tmp_path),
        baseline_snapshot=snapshot(claim_hash, "g0"), baseline_trace=baseline,
        successor_snapshot=snapshot(claim_hash, "g1"), successor_trace=successor,
        intervention=result,
    )
    assert loop.baseline_closure_hash != loop.successor_closure_hash
    assert replay_temporal_loop(ContentAddressedArtifactStore(tmp_path), loop.successor_closure_hash) == (True, ())


def test_temporal_loop_rejects_cfi_failure_and_historical_snapshot_tamper(tmp_path):
    baseline = m6["valid_trace_material"]()
    successor = m6["valid_trace_material"]()
    claim_hash = baseline["router"].claim.claim_hash
    adapter, root, specs, budget, failed_manifest, oracle = m5["experiment"](required=("cache",))
    failed_manifest = CausalExperimentManifest(
        failed_manifest.experiment_id, failed_manifest.schema_version, claim_hash, failed_manifest.root_snapshot_hash,
        failed_manifest.cfi_policy_hash, failed_manifest.arm_specs, failed_manifest.budget_spec_hash,
        failed_manifest.rng_policy, failed_manifest.master_seed, failed_manifest.oracle_spec_hash,
        failed_manifest.evaluator_version, failed_manifest.required_surfaces,
    )
    failed = GenericInterventionKernel().run(failed_manifest, root, specs, budget, adapter, oracle)
    with pytest.raises(ValueError, match="cfi_not_confirmatory"):
        persist_temporal_loop(ContentAddressedArtifactStore(tmp_path), baseline_snapshot=snapshot(claim_hash, "g0"), baseline_trace=baseline, successor_snapshot=snapshot(claim_hash, "g1"), successor_trace=successor, intervention=failed)

    store = ContentAddressedArtifactStore(tmp_path)
    loop = persist_temporal_loop(store, baseline_snapshot=snapshot(claim_hash, "g0"), baseline_trace=baseline, successor_snapshot=snapshot(claim_hash, "g1"), successor_trace=successor, intervention=cfi_pass_result(claim_hash))
    closure = store.get(loop.successor_closure_hash)
    snapshot_hash = next(item["artifact_hashes"][0] for item in closure["artifact_groups"] if item["role"] == "m6c_causal_snapshot")
    store._path(snapshot_hash).write_bytes(b'{"future":"rewrite"}')
    assert replay_temporal_loop(ContentAddressedArtifactStore(tmp_path), loop.successor_closure_hash)[0] is False
