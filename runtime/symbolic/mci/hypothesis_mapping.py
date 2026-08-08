"""Mapeo declarativo de relaciones externas a overlays accionables del MCI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import TransitionSpec


@dataclass(frozen=True)
class EdgeMapping:
    source: str
    target: str
    kind: str
    target_id: str
    precondition_template: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"parameter", "precondition"}:
            raise ValueError("EdgeMapping.kind debe ser parameter o precondition")
        if self.kind == "precondition" and not self.precondition_template:
            raise ValueError("precondition_template es obligatorio para precondition")


class HypothesisMappingRegistry:
    """Registro externo al IR: no modifica la serialización ni el hash del spec."""

    def __init__(self, mappings: Iterable[EdgeMapping] = ()) -> None:
        indexed: dict[tuple[str, str], EdgeMapping] = {}
        for mapping in mappings:
            key = (mapping.source, mapping.target)
            previous = indexed.get(key)
            if previous is not None and previous != mapping:
                raise ValueError(f"Mapeo de arista ambiguo: {key!r}")
            indexed[key] = mapping
        self._mappings = tuple(
            indexed[key] for key in sorted(indexed)
        )

    @property
    def mappings(self) -> tuple[EdgeMapping, ...]:
        return self._mappings

    def resolve(self, source: str, target: str) -> EdgeMapping | None:
        return next(
            (
                mapping
                for mapping in self._mappings
                if mapping.source == source and mapping.target == target
            ),
            None,
        )

    def validate_for(self, spec: TransitionSpec) -> None:
        parameters = set(spec.parameters)
        effects = {
            effect.effect_id
            for equation in spec.equations
            for effect in equation.effects
        }
        for mapping in self._mappings:
            valid_targets = parameters if mapping.kind == "parameter" else effects
            if mapping.target_id not in valid_targets:
                raise ValueError(
                    f"Mapping {mapping.source}->{mapping.target} referencia "
                    f"un target inexistente: {mapping.target_id}"
                )


def default_edge_mappings(spec_id: str) -> tuple[EdgeMapping, ...]:
    """Vocabulario declarado fuera del IR para no alterar su hash."""
    if spec_id == "transition/thermal_with_battery":
        return (
            EdgeMapping(
                source="cooling_active",
                target="temperature",
                kind="parameter",
                target_id="cooling_effect",
            ),
        )
    return ()
