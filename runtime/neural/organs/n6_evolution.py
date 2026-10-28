"""N6: KAN, dinamica LTC y mutacion estructural gobernada."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class KANSpline:
    knots: tuple[float, ...]
    coefficients: tuple[float, ...]
    degree: int = 1

    def __post_init__(self) -> None:
        if self.degree != 1:
            raise ValueError("reference_kan_supports_piecewise_linear_degree_1")
        if len(self.knots) < 2 or len(self.knots) != len(self.coefficients):
            raise ValueError("kan_knots_and_coefficients_must_have_same_length")
        if any(right <= left for left, right in zip(self.knots, self.knots[1:])):
            raise ValueError("kan_knots_must_be_strictly_increasing")

    def evaluate(self, value: float) -> float:
        x = float(value)
        if x <= self.knots[0]:
            return self.coefficients[0]
        if x >= self.knots[-1]:
            return self.coefficients[-1]
        for index, (left, right) in enumerate(zip(self.knots, self.knots[1:])):
            if left <= x <= right:
                ratio = (x - left) / (right - left)
                return self.coefficients[index] * (1.0 - ratio) + self.coefficients[index + 1] * ratio
        raise RuntimeError("kan_interval_not_found")

    def to_sympy(self, symbol: str = "x") -> Any:
        import sympy  # lazy: N0 y los demas organos no dependen de SymPy al importar

        x = sympy.Symbol(symbol)
        pieces = [(sympy.Float(self.coefficients[0]), x <= self.knots[0])]
        for index, (left, right) in enumerate(zip(self.knots, self.knots[1:])):
            ratio = (x - left) / (right - left)
            expression = self.coefficients[index] * (1 - ratio) + self.coefficients[index + 1] * ratio
            pieces.append((sympy.simplify(expression), x <= right))
        pieces.append((sympy.Float(self.coefficients[-1]), True))
        return sympy.Piecewise(*pieces)


@dataclass(frozen=True, slots=True)
class LTCCell:
    input_weights: tuple[tuple[float, ...], ...]
    recurrent_weights: tuple[tuple[float, ...], ...]
    bias: tuple[float, ...]
    tau: tuple[float, ...]

    def __post_init__(self) -> None:
        size = len(self.bias)
        if size == 0 or len(self.recurrent_weights) != size or len(self.input_weights) != size:
            raise ValueError("ltc_shape_mismatch")
        if len(self.tau) != size or any(value <= 0.0 for value in self.tau):
            raise ValueError("ltc_tau_must_be_positive")
        if any(len(row) != size for row in self.recurrent_weights):
            raise ValueError("ltc_recurrent_matrix_must_be_square")

    def step(self, state: Sequence[float], inputs: Sequence[float], *, dt: float) -> tuple[float, ...]:
        if len(state) != len(self.bias) or dt <= 0.0:
            raise ValueError("ltc_state_or_dt_invalid")
        if any(len(row) != len(inputs) for row in self.input_weights):
            raise ValueError("ltc_input_size_mismatch")
        next_state = []
        for index in range(len(state)):
            drive = sum(w * float(x) for w, x in zip(self.input_weights[index], inputs))
            recurrent = sum(w * float(x) for w, x in zip(self.recurrent_weights[index], state))
            target = math.tanh(drive + recurrent + self.bias[index])
            alpha = min(float(dt) / max(self.tau[index], float(dt)), 1.0)
            next_state.append(float(state[index]) + alpha * (target - float(state[index])))
        return tuple(next_state)


@dataclass(frozen=True, slots=True)
class StructuralMutationProposal:
    mutation_type: str
    target: str
    value: Any
    expected_gain: float
    rollback_token: str


class StructuralEvolutionGate:
    ALLOWED_MUTATIONS = {"parameter_bound", "optional_family_budget", "neural_model_version"}

    def evaluate_and_apply(
        self,
        proposal: StructuralMutationProposal,
        *,
        sandbox: Callable[[StructuralMutationProposal], Mapping[str, Any]],
        certify: Callable[[Mapping[str, Any]], bool],
        apply_fn: Callable[[StructuralMutationProposal], Any] | None,
        rollback: Callable[[str], Any] | None,
    ) -> dict[str, Any]:
        if proposal.mutation_type not in self.ALLOWED_MUTATIONS:
            return {"applied": False, "reason": "mutation_type_not_whitelisted"}
        if proposal.expected_gain <= 0.0 or not proposal.rollback_token:
            return {"applied": False, "reason": "positive_gain_and_rollback_token_required"}
        if apply_fn is None or rollback is None:
            return {"applied": False, "reason": "apply_fn_and_rollback_required_p29"}
        report = dict(sandbox(proposal))
        if not certify(report):
            return {"applied": False, "reason": "sandbox_not_certified", "report": report}
        try:
            result = apply_fn(proposal)
        except Exception:
            try:
                rollback(proposal.rollback_token)
            except Exception:
                return {
                    "applied": False,
                    "reason": "apply_failed_rollback_failed",
                    "report": report,
                }
            return {"applied": False, "reason": "apply_failed_rolled_back", "report": report}
        return {"applied": True, "reason": "certified_bounded_mutation", "report": report, "result": result}
