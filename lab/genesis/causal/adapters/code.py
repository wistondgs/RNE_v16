"""Read-only Git identity capture; HEAD alone is never code identity."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from lab.genesis.contracts.serialization import canonical_sha256


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
    return result.stdout


def capture_code(repo_root: str | Path, *, untracked_policy: str = "digest") -> dict[str, Any]:
    root = Path(repo_root).resolve()
    head = _git(root, "rev-parse", "HEAD").strip()
    tracked_diff = _git(root, "diff", "--binary", "HEAD")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    untracked = sorted(line[3:] for line in status.splitlines() if line.startswith("?? "))
    if untracked_policy not in {"digest", "forbid", "ignore"}:
        raise ValueError("genesis_untracked_policy_invalid")
    untracked_result: dict[str, Any] = {"policy": untracked_policy, "count": len(untracked)}
    if untracked_policy == "digest":
        untracked_result["digest"] = canonical_sha256(untracked)
    if untracked_policy == "forbid" and untracked:
        untracked_result["violates_policy"] = True
    payload = {"repo_root": str(root), "head_sha": head, "dirty": bool(status), "tracked_diff_digest": canonical_sha256(tracked_diff), "untracked": untracked_result}
    payload["snapshot_digest"] = canonical_sha256(payload)
    return payload
