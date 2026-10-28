"""Estado dinámico acotado Ω_t del organismo integral."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


DYNAMIC_STATE_SCHEMA_VERSION = "organism-dynamic-state-v1"


def canonical_hash(value: Any) -> str:
    # Import diferido evita acoplar el arranque del paquete organism al coordinador.
    from runtime.neural.integration.contracts import canonical_sha256

    return canonical_sha256(value)


@dataclass(frozen=True, slots=True)
class OrganismDynamicState:
    organism_id: str
    lineage_id: str
    run_id: str
    episode_id: str
    life_step: int
    logical_time: int
    previous_state_hash: str | None
    world: Mapping[str, Any]
    regime: Mapping[str, Any]
    organism: Mapping[str, Any]
    memory: Mapping[str, Any]
    neural: Mapping[str, Any]
    policy: Mapping[str, Any]
    resources: Mapping[str, Any]
    homeostasis: Mapping[str, Any]
    state_hash: str
    schema_version: str = DYNAMIC_STATE_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        organism_id: str,
        lineage_id: str,
        run_id: str,
        episode_id: str,
        life_step: int,
        logical_time: int,
        previous_state_hash: str | None,
        world: Mapping[str, Any],
        regime: Mapping[str, Any],
        organism: Mapping[str, Any],
        memory: Mapping[str, Any],
        neural: Mapping[str, Any],
        policy: Mapping[str, Any],
        resources: Mapping[str, Any],
        homeostasis: Mapping[str, Any],
    ) -> "OrganismDynamicState":
        if not all(str(item or "").strip() for item in (organism_id, lineage_id, run_id, episode_id)):
            raise ValueError("dynamic_state_identity_required")
        if life_step < 0 or logical_time < 0:
            raise ValueError("dynamic_state_logical_time_non_negative")
        payload = {
            "schema_version": DYNAMIC_STATE_SCHEMA_VERSION,
            "organism_id": organism_id,
            "lineage_id": lineage_id,
            "run_id": run_id,
            "episode_id": episode_id,
            "life_step": int(life_step),
            "logical_time": int(logical_time),
            "previous_state_hash": previous_state_hash,
            "world": dict(world),
            "regime": dict(regime),
            "organism": dict(organism),
            "memory": dict(memory),
            "neural": dict(neural),
            "policy": dict(policy),
            "resources": dict(resources),
            "homeostasis": dict(homeostasis),
        }
        return cls(**payload, state_hash=canonical_hash(payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "OrganismDynamicState":
        if raw.get("schema_version") != DYNAMIC_STATE_SCHEMA_VERSION:
            raise ValueError("dynamic_state_schema_mismatch")
        expected = str(raw.get("state_hash") or "")
        state = cls.create(
            organism_id=str(raw.get("organism_id") or ""),
            lineage_id=str(raw.get("lineage_id") or ""),
            run_id=str(raw.get("run_id") or ""),
            episode_id=str(raw.get("episode_id") or ""),
            life_step=int(raw.get("life_step", 0)),
            logical_time=int(raw.get("logical_time", 0)),
            previous_state_hash=raw.get("previous_state_hash"),
            world=dict(raw.get("world") or {}),
            regime=dict(raw.get("regime") or {}),
            organism=dict(raw.get("organism") or {}),
            memory=dict(raw.get("memory") or {}),
            neural=dict(raw.get("neural") or {}),
            policy=dict(raw.get("policy") or {}),
            resources=dict(raw.get("resources") or {}),
            homeostasis=dict(raw.get("homeostasis") or {}),
        )
        if state.state_hash != expected:
            raise ValueError("dynamic_state_hash_mismatch")
        return state


def measured(value: Any, *, status: str | None = None) -> dict[str, Any]:
    """Representa medición sin convertir ausencia en evidencia favorable."""

    if status is not None:
        if status not in {"measured", "unmeasured", "not_applicable", "defaulted"}:
            raise ValueError("dynamic_state_measurement_status_invalid")
        return {"value": value, "measurement_status": status}
    return {
        "value": value,
        "measurement_status": "measured" if value is not None else "unmeasured",
    }
