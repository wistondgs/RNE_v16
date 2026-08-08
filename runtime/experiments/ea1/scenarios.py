from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import stable_id
from .contracts import ContractError, OrdinalState, PublicAction, ScenarioFamily
from .sealing import SealedGroundTruth


@dataclass(frozen=True, slots=True)
class PublicScenario:
    scenario_id: str
    family: ScenarioFamily
    split: str
    actions: tuple[PublicAction, ...]
    passive_observation: OrdinalState
    outcome_horizon: int
    commitment: str

    def __post_init__(self) -> None:
        if len(self.actions) != 6 or len({a.action_id for a in self.actions}) != 6:
            raise ContractError("ea1_requires_exactly_six_actions")

    def to_payload(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "family": self.family, "split": self.split, "actions": self.actions, "passive_observation": self.passive_observation, "outcome_horizon": self.outcome_horizon, "commitment": self.commitment}


@dataclass(frozen=True, slots=True)
class SmokeFixture:
    public: PublicScenario
    sealed_ground_truth: SealedGroundTruth

    def outcome(self, action_id: str, elapsed_steps: int) -> OrdinalState | None:
        hidden = self.sealed_ground_truth.open(self.sealed_ground_truth.evaluator_token(), purpose="evaluator")
        if elapsed_steps < self.public.outcome_horizon:
            return None
        if action_id not in {a.action_id for a in self.public.actions}:
            raise ContractError("unknown_action")
        return OrdinalState(hidden["outcomes"][action_id])


def _deterministic_action_permutation(
    actions: tuple[PublicAction, ...],
    *,
    domain: str,
) -> tuple[PublicAction, ...]:
    permuted = list(actions)
    random.Random(domain).shuffle(permuted)
    return tuple(permuted)


def make_smoke_fixture(family: ScenarioFamily, *, seed: int = 1, split: str = "DEV") -> SmokeFixture:
    if family not in {ScenarioFamily.S1, ScenarioFamily.S2, ScenarioFamily.S3, ScenarioFamily.S5}:
        raise ContractError("smoke_fixture_not_implemented")
    if split not in {"DEV", "DRY"}:
        raise ContractError("p3a_forbids_confirm_fixture_generation")
    scenario_id = stable_id("scenario", {"family": family.value, "seed": seed, "split": split})
    canonical_actions = tuple(
        PublicAction(
            stable_id("action", {"scenario": scenario_id, "slot": i}),
            f"probe-{i + 1}",
            {"channel": i % 3},
        )
        for i in range(6)
    )
    hidden_action_order = _deterministic_action_permutation(
        canonical_actions,
        domain=f"{family.value}:{seed}:{split}",
    )
    public_actions = _deterministic_action_permutation(
        canonical_actions,
        domain=f"{family.value}:{seed}:{split}:public-order-v1",
    )
    discriminating = {
        hidden_action_order[0].action_id,
        hidden_action_order[1].action_id,
    }
    outcomes = {
        action.action_id: (
            OrdinalState.HIGH.value
            if action.action_id in discriminating
            else OrdinalState.MID.value
        )
        for action in canonical_actions
    }
    if family is ScenarioFamily.S5:
        outcomes[hidden_action_order[0].action_id] = OrdinalState.LOW.value
        outcomes[hidden_action_order[1].action_id] = OrdinalState.HIGH.value
    horizon = 2 if family is ScenarioFamily.S3 else 1
    h1_predictions = {
        action.action_id: OrdinalState.MID.value for action in canonical_actions
    }
    h2_predictions = dict(h1_predictions)
    h1_predictions[hidden_action_order[0].action_id], h2_predictions[hidden_action_order[0].action_id] = OrdinalState.LOW.value, OrdinalState.HIGH.value
    h1_predictions[hidden_action_order[1].action_id], h2_predictions[hidden_action_order[1].action_id] = OrdinalState.HIGH.value, OrdinalState.LOW.value
    hidden = {"true_structural_class": f"class-{(seed % 2) + 1}", "hidden_precondition": bool(seed % 2), "discriminating_action_ids": sorted(discriminating), "non_discriminating_action_ids": sorted({a.action_id for a in canonical_actions} - discriminating), "oracle_action_id": hidden_action_order[0].action_id, "outcomes": outcomes, "hypothesis_predictions": {"h1": h1_predictions, "h2": h2_predictions}, "passive_bayes_factor": 1.0, "immediate_rewards": {action.action_id: (1.0 if i == 5 else 0.0) for i, action in enumerate(hidden_action_order)}}
    bundle = SealedGroundTruth(scenario_id, hidden)
    public = PublicScenario(scenario_id, family, split, public_actions, OrdinalState.MID, horizon, bundle.public.commitment)
    return SmokeFixture(public, bundle)
