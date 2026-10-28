"""Allowlisted environment capture with irreversible secret redaction."""

from __future__ import annotations

import os
from typing import Any, Mapping

from lab.genesis.contracts.serialization import canonical_sha256


def capture_environment(allowlist: Mapping[str, bool], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if environ is None else environ
    entries = []
    for name, sensitive in sorted(allowlist.items()):
        present = name in source
        value = source.get(name, "")
        entry: dict[str, Any] = {"name": name, "present": present, "sensitive": bool(sensitive)}
        if present:
            if sensitive:
                entry["value_hash"] = canonical_sha256(value)
            else:
                entry["value"] = value
        entries.append(entry)
    payload = {"allowlist": entries}
    payload["environment_digest"] = canonical_sha256(payload)
    return payload
