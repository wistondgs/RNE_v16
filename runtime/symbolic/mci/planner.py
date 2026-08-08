"""Planner SMT determinista de horizonte acotado."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Mapping

from z3 import Solver, sat

from .compiler import TransitionCompiler
from .contracts import SMTPlanReport


@dataclass(frozen=True)
class MCIPlanningConfig:
    horizon: int = 3
    exact_horizon: bool = False
    objective_mode: str = "terminal_regret"
    max_horizon: int = 5
    effort_cost: float = 0.05
    risk_cost: float = 0.25

    def __post_init__(self) -> None:
        if self.max_horizon < 1 or self.max_horizon > 5:
            raise ValueError("max_horizon debe estar entre 1 y 5")
        if self.horizon < 1 or self.horizon > self.max_horizon:
            raise ValueError("horizon debe estar entre 1 y max_horizon")
        if self.objective_mode not in {"terminal_regret", "trajectory_loss"}:
            raise ValueError("objective_mode no soportado")
        if self.effort_cost < 0.0 or self.risk_cost < 0.0:
            raise ValueError("Los costes del planner deben ser no negativos")


class SMTPlanner:
    def __init__(
        self,
        compiler: TransitionCompiler,
        *,
        horizon: int = 3,
        exact_horizon: bool = False,
        objective_mode: str = "terminal_regret",
        effort_cost: float = 0.05,
        risk_cost: float = 0.25,
    ):
        self.compiler = compiler
        self.horizon = max(1, int(horizon))
        self.exact_horizon = bool(exact_horizon)
        if objective_mode not in {"terminal_regret", "trajectory_loss"}:
            raise ValueError("objective_mode no soportado")
        self.objective_mode = objective_mode
        self.effort_cost = float(effort_cost)
        self.risk_cost = float(risk_cost)

    def plan(
        self,
        state: Mapping[str, Any],
        *,
        external_input: float,
    ) -> SMTPlanReport:
        actions = tuple(sorted(action.name for action in self.compiler.spec.actions))
        candidates: list[tuple[tuple[Any, ...], SMTPlanReport]] = []
        lengths = (
            (self.horizon,)
            if self.exact_horizon
            else range(1, self.horizon + 1)
        )
        for length in lengths:
            for sequence in product(actions, repeat=length):
                report = self.evaluate_sequence(
                    state,
                    actions=sequence,
                    external_input=external_input,
                )
                if report.status != "sat" or report.objective is None:
                    continue
                candidates.append(
                    ((report.objective, length, sequence), report)
                )
        if not candidates:
            return SMTPlanReport(
                status="unsat",
                horizon=self.horizon,
                actions=(),
                projected_states=(),
                objective=None,
                regret=None,
                effort_cost=None,
                risk=None,
                constraint_ids=(),
                objective_mode=(
                    self.objective_mode
                    if self.objective_mode != "terminal_regret"
                    else None
                ),
            )
        return min(candidates, key=lambda item: item[0])[1]

    def evaluate_sequence(
        self,
        state: Mapping[str, Any],
        *,
        actions: tuple[str, ...] | list[str],
        external_input: float,
    ) -> SMTPlanReport:
        """Evalúa una secuencia fija con la misma semántica usada por ``plan``."""
        sequence = tuple(actions)
        if not sequence or len(sequence) > self.horizon:
            return SMTPlanReport(
                status="unsat",
                horizon=self.horizon,
                actions=sequence,
                projected_states=(),
                objective=None,
                regret=None,
                effort_cost=None,
                risk=None,
                constraint_ids=(),
                objective_mode=(
                    self.objective_mode
                    if self.objective_mode != "terminal_regret"
                    else None
                ),
            )
        current = dict(state)
        projected: list[Mapping[str, Any]] = []
        constraint_ids: list[str] = []
        solver = Solver()
        for step, action in enumerate(sequence, 1):
            _, constraints = self.compiler.z3_step(
                current,
                action=action,
                external_input=external_input,
                prefix=f"mci_guard_t{step}",
            )
            for index, constraint in enumerate(constraints):
                solver.add(constraint)
                constraint_ids.append(f"mci/plan/t/{step}/constraint/{index}")
            current = self.compiler.execute(
                current,
                action=action,
                external_input=external_input,
            )
            projected.append(current)
        if solver.check() != sat:
            return SMTPlanReport(
                status="unsat",
                horizon=self.horizon,
                actions=sequence,
                projected_states=tuple(projected),
                objective=None,
                regret=None,
                effort_cost=None,
                risk=None,
                constraint_ids=tuple(constraint_ids),
                objective_mode=(
                    self.objective_mode
                    if self.objective_mode != "terminal_regret"
                    else None
                ),
            )
        regret = self._regret(current)
        risk = self._risk(projected)
        effort = self.effort_cost * len(sequence)
        primary_loss = (
            self._trajectory_loss(projected)
            if self.objective_mode == "trajectory_loss"
            else regret
        )
        objective = round(primary_loss + effort + self.risk_cost * risk, 9)
        return SMTPlanReport(
            status="sat",
            horizon=self.horizon,
            actions=sequence,
            projected_states=tuple(projected),
            objective=objective,
            regret=round(regret, 9),
            effort_cost=round(effort, 9),
            risk=round(risk, 9),
            constraint_ids=tuple(constraint_ids),
            objective_mode=(
                self.objective_mode
                if self.objective_mode != "terminal_regret"
                else None
            ),
        )

    def _trajectory_loss(self, states: list[Mapping[str, Any]]) -> float:
        if not states:
            return 1.0
        spec = self.compiler.spec
        variable = next(
            item for item in spec.variables if item.name == spec.main_variable
        )
        width = float(variable.upper) - float(variable.lower)
        if width <= 0.0:
            raise ValueError("La variable principal debe tener bounds no degenerados")
        losses = []
        for state in states:
            normalized = (
                float(state[spec.main_variable]) - float(variable.lower)
            ) / width
            normalized = max(0.0, min(1.0, normalized))
            losses.append(
                normalized
                if spec.optimization_direction == "minimize"
                else 1.0 - normalized
            )
        return sum(losses) / len(losses)

    def _regret(self, state: Mapping[str, Any]) -> float:
        spec = self.compiler.spec
        value = float(state[spec.main_variable])
        threshold = float(spec.parameters[spec.alarm_threshold_parameter])
        return max(0.0, value - threshold) if spec.optimization_direction == "minimize" else max(
            0.0, threshold - value
        )

    def _risk(self, states: list[Mapping[str, Any]]) -> float:
        if not states:
            return 1.0
        alarms = sum(bool(state[self.compiler.spec.alarm_variable]) for state in states)
        return alarms / len(states)
