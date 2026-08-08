from __future__ import annotations

import json
import random
from dataclasses import replace
from itertools import combinations

from runtime.experiments.ea1.canonical import canonical_value, stable_id
from runtime.experiments.ea1.contracts import OrdinalState, PublicAction, ScenarioFamily
from runtime.experiments.ea1.scenarios import SmokeFixture, make_smoke_fixture


FAMILIES = (ScenarioFamily.S2, ScenarioFamily.S5)
SPLITS = ("DEV", "DRY")
SEEDS = range(1, 101)


def _hidden(fixture: SmokeFixture) -> dict[str, object]:
    token = fixture.sealed_ground_truth.evaluator_token()
    return fixture.sealed_ground_truth.open(token, purpose="evaluator")


def _fixed_matrix():
    for family in FAMILIES:
        for split in SPLITS:
            for seed in SEEDS:
                yield make_smoke_fixture(family, seed=seed, split=split)


def _legacy_hidden_world(family: ScenarioFamily, *, seed: int, split: str) -> dict[str, object]:
    scenario_id = stable_id(
        "scenario", {"family": family.value, "seed": seed, "split": split}
    )
    actions = [
        PublicAction(
            stable_id("action", {"scenario": scenario_id, "slot": index}),
            f"probe-{index + 1}",
            {"channel": index % 3},
        )
        for index in range(6)
    ]
    random.Random(f"{family.value}:{seed}:{split}").shuffle(actions)
    discriminating = {actions[0].action_id, actions[1].action_id}
    outcomes = {
        action.action_id: (
            OrdinalState.HIGH.value
            if action.action_id in discriminating
            else OrdinalState.MID.value
        )
        for action in actions
    }
    if family is ScenarioFamily.S5:
        outcomes[actions[0].action_id] = OrdinalState.LOW.value
        outcomes[actions[1].action_id] = OrdinalState.HIGH.value
    h1_predictions = {
        action.action_id: OrdinalState.MID.value for action in actions
    }
    h2_predictions = dict(h1_predictions)
    h1_predictions[actions[0].action_id] = OrdinalState.LOW.value
    h2_predictions[actions[0].action_id] = OrdinalState.HIGH.value
    h1_predictions[actions[1].action_id] = OrdinalState.HIGH.value
    h2_predictions[actions[1].action_id] = OrdinalState.LOW.value
    return {
        "true_structural_class": f"class-{(seed % 2) + 1}",
        "hidden_precondition": bool(seed % 2),
        "discriminating_action_ids": sorted(discriminating),
        "non_discriminating_action_ids": sorted(
            {action.action_id for action in actions} - discriminating
        ),
        "oracle_action_id": actions[0].action_id,
        "outcomes": outcomes,
        "hypothesis_predictions": {
            "h1": h1_predictions,
            "h2": h2_predictions,
        },
        "passive_bayes_factor": 1.0,
        "immediate_rewards": {
            action.action_id: (1.0 if index == 5 else 0.0)
            for index, action in enumerate(actions)
        },
    }


def test_original_first_two_exploit_is_not_perfect_and_no_pair_replaces_it() -> None:
    successes = {pair: 0 for pair in combinations(range(6), 2)}
    fixtures = tuple(_fixed_matrix())
    assert len(fixtures) == 400

    for fixture in fixtures:
        truth = set(_hidden(fixture)["discriminating_action_ids"])
        for pair in successes:
            predicted = {fixture.public.actions[index].action_id for index in pair}
            successes[pair] += predicted == truth

    assert successes[(0, 1)] < len(fixtures)
    assert all(count < len(fixtures) for count in successes.values())


def test_every_public_position_and_identity_has_both_hidden_roles() -> None:
    position_roles = {index: set() for index in range(6)}
    label_roles = {f"probe-{index + 1}": set() for index in range(6)}

    for fixture in _fixed_matrix():
        discriminating = set(_hidden(fixture)["discriminating_action_ids"])
        for position, action in enumerate(fixture.public.actions):
            role = action.action_id in discriminating
            position_roles[position].add(role)
            label_roles[action.label].add(role)

    assert all(roles == {False, True} for roles in position_roles.values())
    assert all(roles == {False, True} for roles in label_roles.values())


def test_hidden_world_is_exactly_unchanged_from_p3a_for_fixed_seed_matrix() -> None:
    for family in FAMILIES:
        for split in SPLITS:
            for seed in SEEDS:
                fixture = make_smoke_fixture(family, seed=seed, split=split)
                assert _hidden(fixture) == _legacy_hidden_world(
                    family, seed=seed, split=split
                )


def test_public_presentation_is_reproducible_and_contains_no_private_mapping() -> None:
    forbidden = (
        "hidden_role",
        "discriminator",
        "discriminating",
        "secret_rank",
        "source_slot",
        "hidden_index",
        "evaluator_class",
        "role_assignment_seed",
        "inverse_mapping",
    )
    for family in FAMILIES:
        for split in SPLITS:
            for seed in SEEDS:
                first = make_smoke_fixture(family, seed=seed, split=split)
                replay = make_smoke_fixture(family, seed=seed, split=split)
                assert first.public.scenario_id == replay.public.scenario_id
                assert first.public.actions == replay.public.actions
                assert first.public.passive_observation == replay.public.passive_observation
                assert first.public.outcome_horizon == replay.public.outcome_horizon
                assert _hidden(first) == _hidden(replay)
                payload = json.dumps(
                    canonical_value(first.public.to_payload()), sort_keys=True
                ).lower()
                assert not any(term in payload for term in forbidden)


def test_public_permutation_preserves_action_identity_outcome_and_hidden_world() -> None:
    fixture = make_smoke_fixture(ScenarioFamily.S5, seed=37, split="DEV")
    before = _hidden(fixture)
    reversed_public = replace(
        fixture.public, actions=tuple(reversed(fixture.public.actions))
    )
    presented = SmokeFixture(reversed_public, fixture.sealed_ground_truth)

    assert _hidden(presented) == before
    assert {action.action_id for action in presented.public.actions} == {
        action.action_id for action in fixture.public.actions
    }
    for action in fixture.public.actions:
        assert presented.outcome(action.action_id, elapsed_steps=1) == fixture.outcome(
            action.action_id, elapsed_steps=1
        )


def test_s2_s5_causal_integrity_remains_frozen() -> None:
    for fixture in _fixed_matrix():
        hidden = _hidden(fixture)
        discriminating = set(hidden["discriminating_action_ids"])
        non_discriminating = set(hidden["non_discriminating_action_ids"])
        h1 = hidden["hypothesis_predictions"]["h1"]
        h2 = hidden["hypothesis_predictions"]["h2"]

        assert fixture.public.passive_observation is OrdinalState.MID
        assert hidden["passive_bayes_factor"] == 1.0
        assert len(fixture.public.actions) == 6
        assert len(discriminating) == 2
        assert len(non_discriminating) == 4
        assert discriminating.isdisjoint(non_discriminating)
        assert discriminating | non_discriminating == {
            action.action_id for action in fixture.public.actions
        }
        assert {
            action_id for action_id in h1 if h1[action_id] != h2[action_id]
        } == discriminating
        assert all(
            (action.cost, action.risk, action.reversible) == (1, 0.25, True)
            for action in fixture.public.actions
        )
