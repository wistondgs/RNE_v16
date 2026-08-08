"""Contratos inmutables del Módulo de Cognición Integrada."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.symbolic.schemas import _Schema, _freeze, sealed_sha256


@dataclass(frozen=True)
class VariableSpec(_Schema):
    name: str
    kind: str
    lower: float = 0.0
    upper: float = 1.0


@dataclass(frozen=True)
class TermSpec(_Schema):
    source: str
    coefficient: float = 1.0
    parameter: str | None = None


@dataclass(frozen=True)
class EffectSpec(_Schema):
    effect_id: str
    action: str
    delta: float
    parameter: str | None = None
    precondition: str | None = None


@dataclass(frozen=True)
class NeuralHypothesis(_Schema):
    hypothesis_id: str
    kind: str
    target_id: str
    expression: str | None
    proposed_value: float | None
    confidence: float
    evidence_refs: tuple[str, ...]
    provider: str
    model_ref: str
    logical_time: int
    submitted_evidence_refs: tuple[str, ...] = ()
    unresolved_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed = {"precondition", "parameter", "edge", "regime"}
        if self.kind not in allowed:
            raise ValueError(f"Tipo de hipótesis neural inválido: {self.kind}")
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence debe estar entre 0 y 1")
        object.__setattr__(self, "confidence", round(confidence, 6))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(
            self, "submitted_evidence_refs", tuple(self.submitted_evidence_refs)
        )
        object.__setattr__(
            self, "unresolved_evidence_refs", tuple(self.unresolved_evidence_refs)
        )
        if not self.hypothesis_id:
            payload = {
                "kind": self.kind,
                "target_id": self.target_id,
                "expression": self.expression,
                "proposed_value": self.proposed_value,
                "confidence": round(confidence, 6),
                "evidence_refs": tuple(self.evidence_refs),
                "provider": self.provider,
                "model_ref": self.model_ref,
                "logical_time": int(self.logical_time),
            }
            object.__setattr__(
                self, "hypothesis_id", f"neural-{sealed_sha256(payload)[:24]}"
            )


@dataclass(frozen=True)
class NeuralHypothesisEvaluation(_Schema):
    hypothesis_id: str
    status: str
    reason: str
    train_mae_before: float | None
    train_mae_after: float | None
    holdout_mae_before: float | None
    holdout_mae_after: float | None
    promoted_overlay_id: str | None


@dataclass(frozen=True)
class EquationSpec(_Schema):
    target: str
    terms: tuple[TermSpec, ...]
    effects: tuple[EffectSpec, ...] = ()
    clamp: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "terms", tuple(self.terms))
        object.__setattr__(self, "effects", tuple(self.effects))


@dataclass(frozen=True)
class ActionSpec(_Schema):
    name: str
    assignments: Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "assignments", _freeze(self.assignments))


@dataclass(frozen=True)
class InvariantSpec(_Schema):
    variable: str
    operator: str
    threshold_parameter: str


@dataclass(frozen=True)
class TransitionSpec(_Schema):
    spec_id: str
    version: str
    scenario: str
    variables: tuple[VariableSpec, ...]
    parameters: Mapping[str, float]
    actions: tuple[ActionSpec, ...]
    equations: tuple[EquationSpec, ...]
    alarm_variable: str
    alarm_source: str
    alarm_operator: str
    alarm_threshold_parameter: str
    main_variable: str
    optimization_direction: str
    safe_action: str
    invariants: tuple[InvariantSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "variables", tuple(self.variables))
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "equations", tuple(self.equations))
        object.__setattr__(self, "invariants", tuple(self.invariants))
        self.validate()

    @property
    def sha256(self) -> str:
        return sealed_sha256(self.to_dict())

    def validate(self) -> None:
        from .conditions import parse_condition

        variables = {item.name for item in self.variables}
        actions = {item.name for item in self.actions}
        if len(variables) != len(self.variables) or len(actions) != len(self.actions):
            raise ValueError("Variables o acciones duplicadas")
        if self.main_variable not in variables or self.alarm_variable not in variables:
            raise ValueError("Variable principal o alarma no declarada")
        if self.safe_action not in actions:
            raise ValueError("safe_action no declarada")
        if self.optimization_direction not in {"minimize", "maximize"}:
            raise ValueError("Dirección de optimización inválida")
        for equation in self.equations:
            if equation.target not in variables:
                raise ValueError(f"Target no declarado: {equation.target}")
            effect_ids: set[str] = set()
            for effect in equation.effects:
                if effect.effect_id in effect_ids:
                    raise ValueError(f"Effect duplicado: {effect.effect_id}")
                effect_ids.add(effect.effect_id)
                if effect.action not in actions:
                    raise ValueError("Effect referencia una acción desconocida")
                if effect.parameter is not None and effect.parameter not in self.parameters:
                    raise ValueError("Effect referencia un parámetro desconocido")
                if effect.precondition:
                    parse_condition(effect.precondition, variables)


@dataclass(frozen=True)
class CausalOverlay(_Schema):
    overlay_id: str
    version: int
    base_spec_sha256: str
    parameter_updates: Mapping[str, float]
    precondition_updates: Mapping[str, str | None]
    edge_updates: tuple[tuple[str, str, str], ...]
    evidence: Mapping[str, Any]
    train_mae_before: float
    train_mae_after: float
    holdout_mae_before: float
    holdout_mae_after: float
    parent_overlay_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_updates", _freeze(self.parameter_updates))
        object.__setattr__(self, "precondition_updates", _freeze(self.precondition_updates))
        object.__setattr__(self, "edge_updates", tuple(tuple(item) for item in self.edge_updates))
        object.__setattr__(self, "evidence", _freeze(self.evidence))


@dataclass(frozen=True)
class SMTPlanReport(_Schema):
    status: str
    horizon: int
    actions: tuple[str, ...]
    projected_states: tuple[Mapping[str, Any], ...]
    objective: float | None
    regret: float | None
    effort_cost: float | None
    risk: float | None
    constraint_ids: tuple[str, ...]
    tie_breaks: tuple[str, ...] = ("objective", "length", "actions")
    objective_mode: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(
            self, "projected_states", tuple(_freeze(item) for item in self.projected_states)
        )
        object.__setattr__(self, "constraint_ids", tuple(self.constraint_ids))
        object.__setattr__(self, "tie_breaks", tuple(self.tie_breaks))

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.objective_mode is None:
            payload.pop("objective_mode", None)
        return payload


@dataclass(frozen=True)
class Justification(_Schema):
    justification_id: str
    antecedent_ids: tuple[str, ...]
    consequence_id: str
    kind: str


@dataclass(frozen=True)
class BeliefNode(_Schema):
    belief_id: str
    proposition: str
    status: str
    confidence: float
    logical_time: int
    justification_ids: tuple[str, ...]


@dataclass(frozen=True)
class SelfModelReport(_Schema):
    signature: str
    success_probability: float
    expected_cost: float
    invariant_risk: float
    support_count: int
    decision: str
    safe_action: str


@dataclass(frozen=True)
class MCICommitReport(_Schema):
    schema: str
    spec_id: str
    spec_sha256: str
    overlay_id: str | None
    plan: SMTPlanReport
    causal_graph: tuple[tuple[str, str, str, str | None], ...]
    beliefs: tuple[BeliefNode, ...]
    belief_revision: Mapping[str, Any]
    self_model: SelfModelReport
    constraint_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "causal_graph", tuple(tuple(edge) for edge in self.causal_graph)
        )
        object.__setattr__(self, "beliefs", tuple(self.beliefs))
        object.__setattr__(self, "belief_revision", _freeze(self.belief_revision))
        object.__setattr__(self, "constraint_ids", tuple(self.constraint_ids))
