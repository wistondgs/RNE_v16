"""Auto-modelo incremental calibrado por outcomes reales."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .contracts import SelfModelReport, TransitionSpec


class IncrementalSelfModel:
    def __init__(self):
        self._counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self._costs: dict[str, list[float]] = defaultdict(list)

    @staticmethod
    def signature(
        *,
        scenario: str,
        regime: str,
        action: str,
        plan_length: int,
        risk: float,
    ) -> str:
        risk_band = "high" if risk > 0.20 else "medium" if risk > 0.05 else "low"
        return f"{scenario}|{regime}|{action}|h{plan_length}|{risk_band}"

    def predict(
        self,
        *,
        spec: TransitionSpec,
        regime: str,
        action: str,
        plan_length: int,
        risk: float,
    ) -> SelfModelReport:
        signature = self.signature(
            scenario=spec.scenario,
            regime=regime,
            action=action,
            plan_length=plan_length,
            risk=risk,
        )
        successes, failures = self._counts[signature]
        probability = (successes + 1.0) / (successes + failures + 2.0)
        costs = self._costs[signature]
        expected_cost = sum(costs) / len(costs) if costs else float(plan_length)
        decision = "abstain" if probability < 0.60 or risk > 0.20 else "commit"
        return SelfModelReport(
            signature=signature,
            success_probability=round(probability, 6),
            expected_cost=round(expected_cost, 6),
            invariant_risk=round(float(risk), 6),
            support_count=successes + failures,
            decision=decision,
            safe_action=spec.safe_action,
        )

    def observe(self, signature: str, *, success: bool, cost: float) -> None:
        self._counts[signature][0 if success else 1] += 1
        self._costs[signature].append(float(cost))

    def brier_score(self, observations: list[tuple[float, bool]]) -> float | None:
        if not observations:
            return None
        return sum((probability - float(outcome)) ** 2 for probability, outcome in observations) / len(
            observations
        )
