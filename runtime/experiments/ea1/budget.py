from __future__ import annotations

from dataclasses import dataclass

from .contracts import BudgetSnapshot, ContractError, PublicAction


class BudgetExhausted(ContractError):
    pass


@dataclass(frozen=True, slots=True)
class BudgetConsumption:
    consumption_id: str
    before: BudgetSnapshot
    after: BudgetSnapshot


class EpistemicBudget:
    def __init__(self) -> None:
        self._snapshot = BudgetSnapshot(epoch=0, tokens_used=0, cost_used=0, risk_used=0.0)
        self._consumptions: dict[str, BudgetConsumption] = {}

    @property
    def snapshot(self) -> BudgetSnapshot:
        return self._snapshot

    def consume(self, consumption_id: str, action: PublicAction, epoch: int) -> BudgetConsumption:
        existing = self._consumptions.get(consumption_id)
        if existing:
            expected = existing.after
            if expected.epoch != epoch or expected.cost_used - existing.before.cost_used != action.cost or abs(expected.risk_used - existing.before.risk_used - action.risk) > 1e-9:
                raise ContractError("divergent_budget_replay")
            return existing
        before = self._snapshot
        after = BudgetSnapshot(epoch=epoch, tokens_used=before.tokens_used + 1, cost_used=before.cost_used + action.cost, risk_used=round(before.risk_used + action.risk, 10))
        if epoch < 1 or epoch > after.max_epochs or after.tokens_used > after.max_tokens or after.cost_used > after.max_cost or after.risk_used > after.max_risk:
            raise BudgetExhausted("epistemic_budget_exhausted")
        result = BudgetConsumption(consumption_id, before, after)
        self._consumptions[consumption_id] = result
        self._snapshot = after
        return result

    def abstain(self, epoch: int) -> BudgetSnapshot:
        if epoch < 1 or epoch > self._snapshot.max_epochs:
            raise BudgetExhausted("epoch_out_of_range")
        return self._snapshot
