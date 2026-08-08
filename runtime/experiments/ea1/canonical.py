from __future__ import annotations

import hashlib
import json
import math
from dataclasses import is_dataclass
from enum import Enum
from typing import Any, Mapping


class CanonicalizationError(ValueError):
    pass


def canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("non_finite_number")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("mapping_keys_must_be_strings")
        return {key: canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if hasattr(value, "to_payload"):
        return canonical_value(value.to_payload())
    if is_dataclass(value):
        raise CanonicalizationError("dataclass_requires_explicit_to_payload")
    raise CanonicalizationError(f"unsupported_type:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(canonical_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{digest(value)}"
