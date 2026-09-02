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
    UNAVAILABLE = "UNAVAILABLE"
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

    def is_cfi_certifiable(self, required_surfaces: tuple[str, ...] | None = None) -> bool:
        required = set(required_surfaces or REQUIRED_SURFACES)
        return all(surface.name not in required or surface.state in {SurfaceState.CAPTURED, SurfaceState.RESETTABLE, SurfaceState.IMMUTABLE_EXTERNAL} for surface in self.surfaces)


@dataclass(frozen=True, slots=True)
class CFIPolicy:
    required_surfaces: tuple[str, ...]
    confirmatory: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_surfaces", tuple(self.required_surfaces))
        if not set(self.required_surfaces).issubset(REQUIRED_SURFACES):
            raise ValueError("genesis_cfi_policy_unknown_surface")

    def certifies(self, snapshot: CausalSnapshot) -> bool:
        if self.confirmatory:
            code = next(surface for surface in snapshot.surfaces if surface.name == "code")
            if bool(code.detail.get("dirty")):
                return False
        return snapshot.is_cfi_certifiable(self.required_surfaces)


class DriftStatus(str, Enum):
    MATCH = "MATCH"
    DRIFT = "DRIFT"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


def compose_snapshot(*, snapshot_id: str, claim_hash: str, code: Mapping[str, Any], dependencies: Mapping[str, Any], environment: Mapping[str, Any], rng: Mapping[str, Mapping[str, Any]]) -> CausalSnapshot:
    payloads = {"code": code, "dependencies": dependencies, "environment": environment, **rng}
    surfaces = []
    for name in REQUIRED_SURFACES:
        payload = payloads.get(name)
        if payload is None:
            surfaces.append(CausalSurface(name, SurfaceState.UNKNOWN))
        elif name.endswith("_rng"):
            surfaces.append(CausalSurface(name, SurfaceState(payload["state"]), {"digest": payload["digest"]}))
        else:
            surfaces.append(CausalSurface(name, SurfaceState.CAPTURED, {"digest": payload.get("snapshot_digest") or payload.get("manifest_digest") or payload.get("environment_digest"), "dirty": payload.get("dirty", False)}))
    return CausalSnapshot(snapshot_id, "genesis-causal-snapshot-v0", claim_hash, tuple(surfaces), {name: canonical_sha256(value) for name, value in payloads.items()})


def compare_snapshot(expected: CausalSnapshot, current: CausalSnapshot) -> dict[str, DriftStatus]:
    old = {item.name: item for item in expected.surfaces}
    result: dict[str, DriftStatus] = {}
    for item in current.surfaces:
        prior = old[item.name]
        if item.state is SurfaceState.UNKNOWN or prior.state is SurfaceState.UNKNOWN:
            result[item.name] = DriftStatus.UNKNOWN
        elif item.state is SurfaceState.UNAVAILABLE or prior.state is SurfaceState.UNAVAILABLE:
            result[item.name] = DriftStatus.UNAVAILABLE
        elif item.canonical_payload() == prior.canonical_payload():
            result[item.name] = DriftStatus.MATCH
        else:
            result[item.name] = DriftStatus.DRIFT
    return result
