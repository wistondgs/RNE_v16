"""Transition IR declarado para los tres escenarios cognitivos simples."""

from __future__ import annotations

from dataclasses import replace

from .contracts import (
    ActionSpec,
    EffectSpec,
    EquationSpec,
    InvariantSpec,
    TermSpec,
    TransitionSpec,
    VariableSpec,
)


def thermal_spec(*, alarm_threshold: float = 0.85, cooling_effect: float = 0.07) -> TransitionSpec:
    return TransitionSpec(
        spec_id="transition/thermal_homeostasis",
        version="1.0",
        scenario="thermal_homeostasis",
        variables=(
            VariableSpec("temperature", "real"),
            VariableSpec("cooling_active", "bool"),
            VariableSpec("alarm", "bool"),
        ),
        parameters={"alarm_threshold": alarm_threshold, "cooling_effect": cooling_effect},
        actions=(
            ActionSpec("activate_cooling", {"cooling_active": True}),
            ActionSpec("deactivate_cooling", {"cooling_active": False}),
        ),
        equations=(
            EquationSpec(
                "temperature",
                (
                    TermSpec("state.temperature"),
                    TermSpec("external_input"),
                ),
                (
                    EffectSpec(
                        "thermal/cooling",
                        "activate_cooling",
                        -1.0,
                        "cooling_effect",
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


def thermal_battery_spec(
    *,
    alarm_threshold: float = 0.85,
    cooling_effect: float = 0.07,
    battery_discharge_rate: float = 0.06,
    battery_charge_rate: float = 0.01,
) -> TransitionSpec:
    """Modelo inicial deliberadamente incompleto: desconoce la guarda de batería."""
    return TransitionSpec(
        spec_id="transition/thermal_with_battery",
        version="1.0",
        scenario="thermal_with_battery",
        variables=(
            VariableSpec("temperature", "real"),
            VariableSpec("battery_level", "real"),
            VariableSpec("cooling_active", "bool"),
            VariableSpec("alarm", "bool"),
        ),
        parameters={
            "alarm_threshold": alarm_threshold,
            "cooling_effect": cooling_effect,
        },
        actions=(
            ActionSpec("activate_cooling", {"cooling_active": True}),
            ActionSpec("deactivate_cooling", {"cooling_active": False}),
        ),
        equations=(
            EquationSpec(
                "temperature",
                (
                    TermSpec("state.temperature"),
                    TermSpec("external_input"),
                ),
                (
                    EffectSpec(
                        "thermal_battery/cooling",
                        "activate_cooling",
                        -1.0,
                        "cooling_effect",
                    ),
                ),
            ),
            EquationSpec(
                "battery_level",
                (TermSpec("state.battery_level"),),
                (
                    EffectSpec(
                        "thermal_battery/active_consumption",
                        "activate_cooling",
                        -float(battery_discharge_rate),
                    ),
                    EffectSpec(
                        "thermal_battery/passive_recharge",
                        "deactivate_cooling",
                        float(battery_charge_rate),
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
        invariants=(
            InvariantSpec("temperature", "bounds", "alarm_threshold"),
            InvariantSpec("battery_level", "bounds", "alarm_threshold"),
        ),
    )


def resource_spec(*, scarcity_threshold: float = 0.20, production_rate: float = 0.08) -> TransitionSpec:
    return TransitionSpec(
        spec_id="transition/resource_management",
        version="1.0",
        scenario="resource_management",
        variables=(
            VariableSpec("stock_level", "real"),
            VariableSpec("production_active", "bool"),
            VariableSpec("scarcity_alert", "bool"),
        ),
        parameters={
            "scarcity_threshold": scarcity_threshold,
            "production_rate": production_rate,
        },
        actions=(
            ActionSpec("start_production", {"production_active": True}),
            ActionSpec("stop_production", {"production_active": False}),
        ),
        equations=(
            EquationSpec(
                "stock_level",
                (
                    TermSpec("state.stock_level"),
                    TermSpec("external_input", -1.0),
                ),
                (
                    EffectSpec(
                        "resource/production",
                        "start_production",
                        1.0,
                        "production_rate",
                    ),
                ),
            ),
        ),
        alarm_variable="scarcity_alert",
        alarm_source="stock_level",
        alarm_operator="<=",
        alarm_threshold_parameter="scarcity_threshold",
        main_variable="stock_level",
        optimization_direction="maximize",
        safe_action="start_production",
        invariants=(InvariantSpec("stock_level", "bounds", "scarcity_threshold"),),
    )


def deferred_load_spec(
    *,
    alarm_threshold: float = 0.85,
    boost_effect: float = 0.15,
    shed_effect: float = 0.05,
    boost_debt: float = 0.08,
    shed_debt: float = 0.02,
) -> TransitionSpec:
    return TransitionSpec(
        spec_id="transition/deferred_load_trap",
        version="1.0",
        scenario="deferred_load_trap",
        variables=(
            VariableSpec("load", "real"),
            VariableSpec("debt", "real"),
            VariableSpec("boosting", "bool"),
            VariableSpec("alarm", "bool"),
        ),
        parameters={
            "alarm_threshold": alarm_threshold,
            "boost_effect": boost_effect,
            "shed_effect": shed_effect,
            "boost_debt": boost_debt,
            "shed_debt": shed_debt,
        },
        actions=(
            ActionSpec("boost_throughput", {"boosting": True}),
            ActionSpec("shed_load", {"boosting": False}),
        ),
        equations=(
            EquationSpec(
                "debt",
                (TermSpec("state.debt"),),
                (
                    EffectSpec("deferred/boost_debt", "boost_throughput", boost_debt),
                    EffectSpec("deferred/shed_debt", "shed_load", -shed_debt),
                ),
            ),
            EquationSpec(
                "load",
                (
                    TermSpec("state.load"),
                    TermSpec("external_input"),
                    TermSpec("next.debt"),
                ),
                (
                    EffectSpec("deferred/boost_load", "boost_throughput", -boost_effect),
                    EffectSpec("deferred/shed_load", "shed_load", -shed_effect),
                ),
            ),
        ),
        alarm_variable="alarm",
        alarm_source="load",
        alarm_operator=">=",
        alarm_threshold_parameter="alarm_threshold",
        main_variable="load",
        optimization_direction="minimize",
        safe_action="shed_load",
        invariants=(
            InvariantSpec("load", "bounds", "alarm_threshold"),
            InvariantSpec("debt", "bounds", "alarm_threshold"),
        ),
    )


def with_overlay(
    spec: TransitionSpec,
    parameter_updates: dict[str, float],
    precondition_updates: dict[str, str | None] | None = None,
) -> TransitionSpec:
    unknown = set(parameter_updates) - set(spec.parameters)
    if unknown:
        raise ValueError(f"Parámetros desconocidos: {sorted(unknown)}")
    conditions = dict(precondition_updates or {})
    known_effects = {
        effect.effect_id for equation in spec.equations for effect in equation.effects
    }
    unknown_effects = set(conditions) - known_effects
    if unknown_effects:
        raise ValueError(f"Effects desconocidos: {sorted(unknown_effects)}")
    equations = tuple(
        replace(
            equation,
            effects=tuple(
                replace(effect, precondition=conditions.get(effect.effect_id, effect.precondition))
                for effect in equation.effects
            ),
        )
        for equation in spec.equations
    )
    return replace(
        spec,
        parameters={**dict(spec.parameters), **parameter_updates},
        equations=equations,
    )
