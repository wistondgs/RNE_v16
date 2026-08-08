from __future__ import annotations

import pytest

from runtime.symbolic.mci import (
    MCIPlanningConfig,
    MCIRuntime,
    SMTPlanner,
    TransitionCompiler,
    deferred_load_spec,
)
from runtime.symbolic.mci.contracts import (
    ActionSpec,
    EquationSpec,
    InvariantSpec,
    TermSpec,
    TransitionSpec,
    VariableSpec,
)
from runtime.symbolic.schemas import canonical_json


DEFERRED_STATE = {
    "load": 0.7,
    "debt": 0.0,
    "boosting": False,
    "alarm": False,
}


def test_legacy_configuration_is_byte_identical():
    compiler = TransitionCompiler(deferred_load_spec())
    implicit = SMTPlanner(compiler).plan(DEFERRED_STATE, external_input=0.04)
    explicit = SMTPlanner(
        compiler,
        horizon=3,
        exact_horizon=False,
        objective_mode="terminal_regret",
        effort_cost=0.05,
        risk_cost=0.25,
    ).plan(DEFERRED_STATE, external_input=0.04)

    assert canonical_json(implicit.to_dict()) == canonical_json(explicit.to_dict())
    assert "objective_mode" not in implicit.to_dict()


def test_exact_horizon_trajectory_loss_sees_deferred_consequence():
    planner = SMTPlanner(
        TransitionCompiler(deferred_load_spec()),
        horizon=3,
        exact_horizon=True,
        objective_mode="trajectory_loss",
    )
    plan = planner.plan(DEFERRED_STATE, external_input=0.04)
    baseline = planner.evaluate_sequence(
        DEFERRED_STATE,
        actions=("boost_throughput",) * 3,
        external_input=0.04,
    )

    assert plan.actions == ("shed_load", "shed_load", "boost_throughput")
    assert len(plan.projected_states) == 3
    assert plan.objective is not None and baseline.objective is not None
    assert plan.objective < baseline.objective
    assert plan.objective_mode == "trajectory_loss"


def test_runtime_and_planner_share_identical_sequence_objective():
    config = MCIPlanningConfig(
        horizon=3,
        exact_horizon=True,
        objective_mode="trajectory_loss",
    )
    runtime = MCIRuntime(deferred_load_spec(), planning_config=config)
    sequence = ("shed_load", "shed_load", "boost_throughput")
    runtime_report = runtime.evaluate_plan_sequence(
        DEFERRED_STATE,
        actions=sequence,
        external_input=0.04,
    )
    planner_report = SMTPlanner(
        TransitionCompiler(runtime.learner.active_spec),
        horizon=config.horizon,
        exact_horizon=config.exact_horizon,
        objective_mode=config.objective_mode,
        effort_cost=config.effort_cost,
        risk_cost=config.risk_cost,
    ).evaluate_sequence(
        DEFERRED_STATE,
        actions=sequence,
        external_input=0.04,
    )

    assert runtime_report.to_dict() == planner_report.to_dict()


def test_trajectory_loss_uses_declared_non_unit_bounds():
    spec = TransitionSpec(
        spec_id="transition/non_unit_bounds",
        version="1",
        scenario="non_unit_bounds",
        variables=(
            VariableSpec("value", "real", lower=10.0, upper=100.0),
            VariableSpec("active", "bool"),
            VariableSpec("alarm", "bool"),
        ),
        parameters={"threshold": 100.0},
        actions=(ActionSpec("hold", {"active": False}),),
        equations=(
            EquationSpec("value", (TermSpec("state.value"),)),
        ),
        alarm_variable="alarm",
        alarm_source="value",
        alarm_operator=">=",
        alarm_threshold_parameter="threshold",
        main_variable="value",
        optimization_direction="minimize",
        safe_action="hold",
        invariants=(InvariantSpec("value", "bounds", "threshold"),),
    )
    report = SMTPlanner(
        TransitionCompiler(spec),
        horizon=1,
        exact_horizon=True,
        objective_mode="trajectory_loss",
    ).evaluate_sequence(
        {"value": 55.0, "active": False, "alarm": False},
        actions=("hold",),
        external_input=0.0,
    )

    assert report.objective == pytest.approx(0.55)
    assert report.effort_cost == pytest.approx(0.05)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"horizon": 0},
        {"horizon": 6},
        {"max_horizon": 0},
        {"max_horizon": 6},
        {"objective_mode": "invalid"},
        {"effort_cost": -1.0},
        {"risk_cost": -1.0},
    ),
)
def test_invalid_planning_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MCIPlanningConfig(**kwargs)
