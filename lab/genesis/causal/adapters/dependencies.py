"""Deterministic local dependency manifest; it deliberately omits OS/container layers."""

from __future__ import annotations

import platform
import sys
from importlib import metadata
from typing import Any

from lab.genesis.contracts.serialization import canonical_sha256


def capture_dependencies() -> dict[str, Any]:
    packages = sorted({(dist.metadata["Name"] or "").lower(): dist.version for dist in metadata.distributions() if dist.metadata.get("Name")}.items())
    payload: dict[str, Any] = {"python_implementation": platform.python_implementation(), "python_version": platform.python_version(), "platform_system": platform.system(), "platform_release": platform.release(), "packages": [{"name": name, "version": version} for name, version in packages], "not_covered": ("cuda_runtime", "system_libraries", "container_image", "external_binaries")}
    payload["manifest_digest"] = canonical_sha256(payload)
    return payload
