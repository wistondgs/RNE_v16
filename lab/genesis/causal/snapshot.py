"""CFI-v0 manifests: unknown surfaces are explicit and non-certifiable."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from lab.genesis.contracts.serialization import canonical_sha256, freeze


REQUIRED_SURFACES = ("code", "dependencies", "environment", "python_rng", "numpy_rng", "torch_cpu_rng", "torch_cuda_rng", "storage", "memory", "retrieval", "cache", "model", "adapters", "visible_context", "tools", "permissions", "resources", "verifiers")


class SurfaceState(str, Enum):
    CAPTURED = "CAPTURED"
    RESETTABLE = "RESETTABLE"
    IMMUTABLE_EXTERNAL = "IMMUTABLE_EXTERNAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CausalSurface:
    name: str
    state: SurfaceState
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", SurfaceState(self.state))
        object.__setattr__(self, "detail", freeze(self.detail))

    def canonical_payload(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CausalSnapshot:
    snapshot_id: str
    schema_version: str
    claim_hash: str
    surfaces: tuple[CausalSurface, ...]
    payload_hashes: Mapping[str, str]
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "surfaces", tuple(self.surfaces))
        names = tuple(surface.name for surface in self.surfaces)
        if set(names) != set(REQUIRED_SURFACES) or len(names) != len(REQUIRED_SURFACES):
            raise ValueError("genesis_snapshot_requires_all_causal_surfaces")
        object.__setattr__(self, "payload_hashes", freeze(self.payload_hashes))
        object.__setattr__(self, "snapshot_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "schema_version": self.schema_version, "claim_hash": self.claim_hash, "surfaces": tuple(item.canonical_payload() for item in self.surfaces), "payload_hashes": self.payload_hashes}

    def is_cfi_certifiable(self) -> bool:
        return all(surface.state is not SurfaceState.UNKNOWN for surface in self.surfaces)
