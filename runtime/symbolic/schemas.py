"""Contratos inmutables y serialización canónica para trazas actuantes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Los valores no finitos no son serializables")
    return value


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Los valores no finitos no son serializables")
    return value


def canonical_json(value: Any) -> str:
    """Devuelve JSON estable, compacto y estricto."""

    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def append_canonical_jsonl(path: str | Path, value: object) -> Path:
    """Añade un registro usando la única primitiva JSONL de SYM-0."""

    return append_canonical_jsonl_many(path, (value,))


def append_canonical_jsonl_many(
    path: str | Path, values: Iterable[object]
) -> Path:
    """Añade varios registros con una sola apertura del archivo."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(canonical_json(value) + "\n")
    return target


class _Schema:
    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True)
class ConstraintRecord(_Schema):
    constraint_id: str
    expression: str
    hard_or_revisable: str
    provenance: Mapping[str, Any]
    parent_ids: tuple[str, ...]
    logical_time: int
    replay_unit_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", _freeze(self.provenance))
        object.__setattr__(self, "parent_ids", tuple(self.parent_ids))


@dataclass(frozen=True)
class CoreReport(_Schema):
    replay_unit_id: str
    logical_time: int
    status: str
    core_ids: tuple[str, ...]
    all_constraint_ids: tuple[str, ...]
    model: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "core_ids", tuple(self.core_ids))
        object.__setattr__(self, "all_constraint_ids", tuple(self.all_constraint_ids))
        if self.model is not None:
            object.__setattr__(self, "model", _freeze(self.model))


@dataclass(frozen=True)
class OptimizationCandidate(_Schema):
    intervention: str
    steps: int
    projected: float
    objective: float
    effort_cost: float


@dataclass(frozen=True)
class OptimizationDecisionReport(_Schema):
    x0: float | None
    direction: str
    candidates: tuple[OptimizationCandidate, ...]
    winner: OptimizationCandidate | None
    tie_breaks: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "tie_breaks", tuple(self.tie_breaks))


@dataclass(frozen=True)
class CausalGuardReport(_Schema):
    fired: bool
    from_intervention: str | None
    to_intervention: str | None
    margin_gain: float
    guard_reason: str
    conflict_evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "margin_gain", round(float(self.margin_gain), 6))
        object.__setattr__(self, "conflict_evidence", _freeze(self.conflict_evidence))


@dataclass(frozen=True)
class ActingDecisionTrace(_Schema):
    replay_unit_id: str
    preaction_logical_time: int
    core_report: CoreReport | None
    opt_report: OptimizationDecisionReport | None
    guard_report: CausalGuardReport
    baseline_action: str
    committed_action: str
    governance_verdict: Mapping[str, Any]
    sealed_hash: str
    mci_evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "governance_verdict", _freeze(self.governance_verdict))
        if self.mci_evidence is not None:
            object.__setattr__(self, "mci_evidence", _freeze(self.mci_evidence))

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.mci_evidence is None:
            payload.pop("mci_evidence", None)
        return payload


@dataclass(frozen=True)
class ActingOutcomeLink(_Schema):
    decision_trace_sha256: str
    outcome_observed: Mapping[str, Any]
    prediction_error: float | None
    utility: float | None
    certification_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_observed", _freeze(self.outcome_observed))


def sealed_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
