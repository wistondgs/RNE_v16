from __future__ import annotations

from runtime.symbolic.mci.causal_learning import (
    CausalLearningEngine,
    TransitionEvidence,
)
from runtime.symbolic.mci.compiler import TransitionCompiler
from runtime.symbolic.mci.contracts import (
    ActionSpec,
    EffectSpec,
    EquationSpec,
    InvariantSpec,
    TermSpec,
    TransitionSpec,
    VariableSpec,
)
from runtime.symbolic.mci.specs import with_overlay


def _battery_spec() -> TransitionSpec:
    return TransitionSpec(
        spec_id="transition/synthetic_battery",
        version="1.0",
        scenario="synthetic_battery",
        variables=(
            VariableSpec("temperature", "real"),
            VariableSpec("battery_level", "real"),
            VariableSpec("cooling_active", "bool"),
            VariableSpec("alarm", "bool"),
        ),
        parameters={"alarm_threshold": 0.85, "cooling_effect": 0.10},
        actions=(ActionSpec("activate_cooling", {"cooling_active": True}),),
        equations=(
            EquationSpec(
                target="temperature",
                terms=(TermSpec("state.temperature"),),
                effects=(
                    EffectSpec(
                        effect_id="synthetic/cooling",
                        action="activate_cooling",
                        delta=-1.0,
                        parameter="cooling_effect",
                    ),
                ),
            ),
        ),
        alarm_variable="alarm",
        alarm_source="temperature",
        alarm_operator=">=",
        alarm_threshold_parameter="alarm_threshold",
        main_variable="temperature",
        optimization_direction="minimize",
        safe_action="activate_cooling",
        invariants=(InvariantSpec("temperature", "bounds", "alarm_threshold"),),
    )


def test_hidden_precondition_is_discovered_validated_and_promoted():
    base = _battery_spec()
    actual = with_overlay(
        base, {}, {"synthetic/cooling": "battery_level > 0.3"}
    )
    learner = CausalLearningEngine(base)
    promoted = None
    for episode in range(20):
        battery = 0.1 if episode % 2 == 0 else 0.8
        state = {
            "temperature": 0.9,
            "battery_level": battery,
            "cooling_active": False,
            "alarm": True,
        }
        predicted = TransitionCompiler(learner.active_spec).execute(
            state, action="activate_cooling", external_input=0.0
        )
        observed = TransitionCompiler(actual).execute(
            state, action="activate_cooling", external_input=0.0
        )
        promoted = learner.observe(
            TransitionEvidence(
                state=state,
                action="activate_cooling",
                external_input=0.0,
                observed=observed,
                predicted=predicted,
            )
        ) or promoted

    assert promoted is not None
    condition = promoted.precondition_updates["synthetic/cooling"]
    assert condition is not None
    assert "battery_level >" in condition
    assert promoted.holdout_mae_after < promoted.holdout_mae_before

    compiler = TransitionCompiler(learner.active_spec)
    low = compiler.execute(
        {
            "temperature": 0.9,
            "battery_level": 0.1,
            "cooling_active": False,
            "alarm": True,
        },
        action="activate_cooling",
        external_input=0.0,
    )
    high = compiler.execute(
        {
            "temperature": 0.9,
            "battery_level": 0.8,
            "cooling_active": False,
            "alarm": True,
        },
        action="activate_cooling",
        external_input=0.0,
    )
    assert low["temperature"] == 0.9
    assert high["temperature"] == 0.8
    assert any(edge[3] == condition for edge in compiler.causal_graph())
