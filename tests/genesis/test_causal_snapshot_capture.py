from __future__ import annotations

import random
import subprocess
from pathlib import Path

import pytest

from lab.genesis.causal import CFIPolicy, DriftStatus, REQUIRED_SURFACES, SurfaceState, compare_snapshot, compose_snapshot
from lab.genesis.causal.adapters import capture_code, capture_dependencies, capture_environment, capture_rng, restore_rng


def _captured(tmp_path: Path):
    code = capture_code(Path(__file__).parents[2])
    deps = capture_dependencies()
    env = capture_environment({"GENESIS_VISIBLE": False, "GENESIS_SECRET": True}, {"GENESIS_VISIBLE": "one", "GENESIS_SECRET": "do-not-leak", "IGNORED": "x"})
    rng = capture_rng()
    return compose_snapshot(snapshot_id="s0", claim_hash="claim", code=code, dependencies=deps, environment=env, rng=rng), code, deps, env, rng


def test_environment_allowlist_redacts_secrets_and_detects_drift(tmp_path):
    _, _, _, one, _ = _captured(tmp_path)
    two = capture_environment({"GENESIS_VISIBLE": False, "GENESIS_SECRET": True}, {"GENESIS_VISIBLE": "two", "GENESIS_SECRET": "do-not-leak", "IGNORED": "changed"})
    assert one["environment_digest"] != two["environment_digest"]
    assert "do-not-leak" not in str(one)
    assert "IGNORED" not in str(one)


def test_code_distinguishes_head_and_dirty_state(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    (tmp_path / "a.txt").write_text("one")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    clean = capture_code(tmp_path)
    (tmp_path / "a.txt").write_text("two")
    dirty = capture_code(tmp_path)
    assert clean["head_sha"] == dirty["head_sha"]
    assert clean["snapshot_digest"] != dirty["snapshot_digest"]
    assert dirty["dirty"] is True


def test_dependency_stable_rng_restore_and_snapshot_drift(tmp_path):
    snapshot, code, deps, env, rng = _captured(tmp_path)
    assert deps == capture_dependencies()
    restore_rng(rng)
    first = [random.random() for _ in range(4)]
    restore_rng(rng)
    assert first == [random.random() for _ in range(4)]
    changed_env = capture_environment({"GENESIS_VISIBLE": False, "GENESIS_SECRET": True}, {"GENESIS_VISIBLE": "changed", "GENESIS_SECRET": "do-not-leak"})
    current = compose_snapshot(snapshot_id="s0", claim_hash="claim", code=code, dependencies=deps, environment=changed_env, rng=rng)
    assert compare_snapshot(snapshot, current)["environment"] is DriftStatus.DRIFT


def test_required_surfaces_policy_and_unknown_vs_unavailable(tmp_path):
    snapshot, *_ = _captured(tmp_path)
    assert CFIPolicy(("code", "dependencies", "environment", "python_rng"), confirmatory=False).certifies(snapshot)
    assert not CFIPolicy(("cache",)).certifies(snapshot)
    rng = capture_rng()
    assert rng["numpy_rng"]["state"] in {SurfaceState.RESETTABLE.value, SurfaceState.UNAVAILABLE.value, SurfaceState.UNKNOWN.value}
    assert set(item.name for item in snapshot.surfaces) == set(REQUIRED_SURFACES)
