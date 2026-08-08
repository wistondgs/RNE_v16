"""Compiladores Python, SMT y causal desde Transition IR."""

from __future__ import annotations

from typing import Any, Mapping

from z3 import Bool, BoolVal, If, Real, RealVal

from .conditions import compile_condition, evaluate_condition
from .contracts import EquationSpec, TransitionSpec


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


class TransitionCompiler:
    def __init__(self, spec: TransitionSpec):
        self.spec = spec
        self._variables = {item.name: item for item in spec.variables}
        self._actions = {item.name: item for item in spec.actions}

    def execute(
        self,
        state: Mapping[str, Any],
        *,
        action: str,
        external_input: float,
    ) -> dict[str, Any]:
        if action not in self._actions:
            raise ValueError(f"Acción no declarada: {action}")
        result = dict(state)
        result.update(dict(self._actions[action].assignments))
        for equation in self.spec.equations:
            value = self._evaluate_equation(
                equation, state=state, result=result, action=action, external_input=external_input
            )
            variable = self._variables[equation.target]
            result[equation.target] = _clamp(value, variable.lower, variable.upper) if equation.clamp else value
        threshold = float(self.spec.parameters[self.spec.alarm_threshold_parameter])
        source = float(result[self.spec.alarm_source])
        result[self.spec.alarm_variable] = (
            source >= threshold if self.spec.alarm_operator == ">=" else source <= threshold
        )
        return {item.name: result[item.name] for item in self.spec.variables}

    def _evaluate_equation(
        self,
        equation: EquationSpec,
        *,
        state: Mapping[str, Any],
        result: Mapping[str, Any],
        action: str,
        external_input: float,
    ) -> float:
        total = 0.0
        for term in equation.terms:
            if term.source == "external_input":
                raw = external_input
            elif term.source.startswith("state."):
                raw = state[term.source.split(".", 1)[1]]
            elif term.source.startswith("next."):
                raw = result[term.source.split(".", 1)[1]]
            else:
                raise ValueError(f"Fuente no soportada: {term.source}")
            coefficient = term.coefficient
            if term.parameter is not None:
                coefficient *= float(self.spec.parameters[term.parameter])
            total += float(raw) * coefficient
        condition_state = {**dict(state), **dict(result)}
        for effect in equation.effects:
            if effect.action != action or not evaluate_condition(
                effect.precondition, condition_state
            ):
                continue
            magnitude = effect.delta
            if effect.parameter is not None:
                magnitude *= float(self.spec.parameters[effect.parameter])
            total += magnitude
        return total

    def causal_graph(self) -> tuple[tuple[str, str, str, str | None], ...]:
        edges: set[tuple[str, str, str, str | None]] = set()
        for equation in self.spec.equations:
            for term in equation.terms:
                source = term.source.split(".", 1)[-1]
                coefficient = term.coefficient
                if term.parameter is not None:
                    coefficient *= float(self.spec.parameters[term.parameter])
                edges.add((source, equation.target, "+" if coefficient >= 0 else "-", None))
            for effect in equation.effects:
                magnitude = effect.delta
                if effect.parameter is not None:
                    magnitude *= float(self.spec.parameters[effect.parameter])
                edges.add(
                    (
                        effect.action,
                        equation.target,
                        "+" if magnitude >= 0 else "-",
                        effect.precondition,
                    )
                )
        edges.add(
            (
                self.spec.alarm_source,
                self.spec.alarm_variable,
                self.spec.alarm_operator,
                None,
            )
        )
        return tuple(sorted(edges))

    def z3_step(
        self,
        state: Mapping[str, Any],
        *,
        action: str,
        external_input: float,
        prefix: str,
    ) -> tuple[dict[str, Any], tuple[Any, ...]]:
        if action not in self._actions:
            raise ValueError(f"Acción no declarada: {action}")
        symbols: dict[str, Any] = {
            variable.name: (
                Bool(f"{prefix}_{variable.name}")
                if variable.kind == "bool"
                else Real(f"{prefix}_{variable.name}")
            )
            for variable in self.spec.variables
        }
        expressions: dict[str, Any] = {}
        for name, value in self._actions[action].assignments.items():
            expressions[name] = BoolVal(bool(value))
        for equation in self.spec.equations:
            expression = RealVal("0")
            for term in equation.terms:
                if term.source == "external_input":
                    raw = RealVal(str(float(external_input)))
                elif term.source.startswith("state."):
                    name = term.source.split(".", 1)[1]
                    raw_value = state[name]
                    raw = RealVal(
                        "1" if self._variables[name].kind == "bool" and raw_value else
                        "0" if self._variables[name].kind == "bool" else
                        str(float(raw_value))
                    )
                elif term.source.startswith("next."):
                    name = term.source.split(".", 1)[1]
                    raw = expressions[name]
                    if self._variables[name].kind == "bool":
                        raw = If(raw, RealVal("1"), RealVal("0"))
                else:
                    raise ValueError(f"Fuente no soportada: {term.source}")
                coefficient = term.coefficient
                if term.parameter is not None:
                    coefficient *= float(self.spec.parameters[term.parameter])
                expression = expression + raw * RealVal(str(float(coefficient)))
            condition_values = {
                variable.name: (
                    BoolVal(bool(state[variable.name]))
                    if variable.kind == "bool"
                    else RealVal(str(float(state[variable.name])))
                )
                for variable in self.spec.variables
                if variable.name in state
            }
            condition_values.update(expressions)
            for effect in equation.effects:
                if effect.action != action:
                    continue
                magnitude = effect.delta
                if effect.parameter is not None:
                    magnitude *= float(self.spec.parameters[effect.parameter])
                condition = compile_condition(effect.precondition, condition_values)
                expression = expression + If(
                    condition, RealVal(str(float(magnitude))), RealVal("0")
                )
            variable = self._variables[equation.target]
            if equation.clamp:
                lower = RealVal(str(float(variable.lower)))
                upper = RealVal(str(float(variable.upper)))
                expression = If(expression < lower, lower, If(expression > upper, upper, expression))
            expressions[equation.target] = expression
        threshold = RealVal(
            str(float(self.spec.parameters[self.spec.alarm_threshold_parameter]))
        )
        source = expressions.get(
            self.spec.alarm_source,
            RealVal(str(float(state[self.spec.alarm_source]))),
        )
        expressions[self.spec.alarm_variable] = (
            source >= threshold if self.spec.alarm_operator == ">=" else source <= threshold
        )
        constraints: list[Any] = []
        for variable in self.spec.variables:
            value = expressions.get(variable.name)
            if value is None:
                current = state[variable.name]
                value = (
                    BoolVal(bool(current))
                    if variable.kind == "bool"
                    else RealVal(str(float(current)))
                )
            constraints.append(
                symbols[variable.name] == value
            )
        return symbols, tuple(constraints)
