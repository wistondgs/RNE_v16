"""Runtime-neutral canonical serialization for Genesis evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields, is_dataclass
from types import MappingProxyType
from typing import Any, Mapping


def freeze(value: Any) -> Any:
    """Recursively detach mutable contract inputs."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("genesis_nonfinite_value")
    return value


def _plain(value: Any) -> Any:
    if hasattr(value, "canonical_payload"):
        return _plain(value.canonical_payload())
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("genesis_nonfinite_value")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic, strict UTF-8 JSON bytes."""
    return json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
