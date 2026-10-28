"""Ventanas longitudinales ordenadas sobre la cadena vital, nunca IID."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .dynamic_state import canonical_hash
from .life_transition import LifeTransition


TRAJECTORY_WINDOW_SCHEMA_VERSION = "organism-trajectory-window-v1"


@dataclass(frozen=True, slots=True)
class DynamicTrajectoryWindow:
    window_id: str
    organism_id: str
    lineage_id: str
    chain_epoch: int
    start_transition_index: int
    end_transition_index: int
    transitions: tuple[LifeTransition, ...]
    closed: bool = True
    schema_version: str = TRAJECTORY_WINDOW_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


class TrajectoryWindowBuilder:
    def __init__(self, transitions: Iterable[LifeTransition], *, chain_epoch: int):
        self.transitions = tuple(transitions)
        self.chain_epoch = int(chain_epoch)
        self._validate()

    def _validate(self) -> None:
        if not self.transitions:
            return
        organism = self.transitions[0].state_before.organism_id
        lineage = self.transitions[0].state_before.lineage_id
        for item in self.transitions:
            if item.status != "committed":
                raise ValueError("trajectory_window_requires_committed_transitions")
            if item.state_before.organism_id != organism or item.state_after.organism_id != organism:
                raise ValueError("trajectory_window_mixed_organisms")
            if item.state_before.lineage_id != lineage or item.state_after.lineage_id != lineage:
                raise ValueError("trajectory_window_mixed_lineages")
        for previous, current in zip(self.transitions, self.transitions[1:]):
            if current.transition_index != previous.transition_index + 1:
                raise ValueError("trajectory_window_non_monotonic")
            if current.previous_transition_hash != previous.transition_hash:
                raise ValueError("trajectory_window_chain_hash_gap")
            if current.state_before.previous_state_hash != previous.state_after.state_hash:
                raise ValueError("trajectory_window_state_hash_gap")

    def latest(self, *, size: int) -> DynamicTrajectoryWindow:
        if not self.transitions:
            raise ValueError("trajectory_window_requires_transitions")
        compatible_suffix = self.transitions
        for index, transition in enumerate(self.transitions):
            compatibility = transition.regime_after.get(
                "compatibility_with_previous_regime"
            )
            transformation = transition.regime_after.get("transformation_applied")
            if compatibility == "non_transportable" or (
                compatibility == "transformable_regime" and not transformation
            ):
                compatible_suffix = self.transitions[index:]
        selected = compatible_suffix[-max(1, int(size)) :]
        identity = {
            "chain_epoch": self.chain_epoch,
            "transition_hashes": [item.transition_hash for item in selected],
        }
        return DynamicTrajectoryWindow(
            window_id=f"trajectory-window-{canonical_hash(identity)[:24]}",
            organism_id=selected[0].state_before.organism_id,
            lineage_id=selected[0].state_before.lineage_id,
            chain_epoch=self.chain_epoch,
            start_transition_index=selected[0].transition_index,
            end_transition_index=selected[-1].transition_index,
            transitions=selected,
        )
