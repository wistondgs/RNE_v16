"""Core-only subset recovered from test_mci_integrated.py at 2b32e5d."""

from __future__ import annotations

import random

import pytest
from z3 import Solver, sat

from runtime.symbolic.mci import (
    CausalLearningEngine,
    IncrementalSelfModel,
    Justification,
    MCIRuntime,
    SMTPlanner,
    TemporalAssumptionLedger,
    TransitionCompiler,
    TransitionEvidence,
    deferred_load_spec,
    resource_spec,
    thermal_spec,
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@pytest.mark.parametrize(
    ("spec", "oracle"),
    [
        (
            thermal_spec(),
            lambda s, a, x: {
                "temperature": _clamp(
                    s["temperature"] + x - (0.07 if a == "activate_cooling" else 0.0)
                ),
                "cooling_active": a == "activate_cooling",
            },
        ),
        (
            resource_spec(scarcity_threshold=0.20),
            lambda s, a, x: {
                "stock_level": _clamp(
                    s["stock_level"] - x + (0.08 if a == "start_production" else 0.0)
                ),
                "production_active": a == "start_production",
            },
        ),
        (
            deferred_load_spec(shed_effect=0.05, shed_debt=0.02),
            lambda s, a, x: {
                "debt": _clamp(s["debt"] + (0.08 if a == "boost_throughput" else -0.02)),
                "boosting": a == "boost_throughput",
            },
        ),
    ],
)
def test_ir_python_and_smt_equivalence_10k(spec, oracle):
    rng = random.Random(417)
    compiler = TransitionCompiler(spec)
    actions = [item.name for item in spec.actions]
    for index in range(10_000):
        state = {
            item.name: (bool(rng.getrandbits(1)) if item.kind == "bool" else rng.random())
            for item in spec.variables
        }
        action = actions[index % len(actions)]
        external = rng.uniform(-0.2, 0.2)
        expected = oracle(state, action, external)
        if spec.scenario == "deferred_load_trap":
            expected["load"] = _clamp(
                state["load"]
                + external
                + (-0.15 if action == "boost_throughput" else -0.05)
                + expected["debt"]
            )
        threshold = float(spec.parameters[spec.alarm_threshold_parameter])
        alarm_source = expected[spec.main_variable]
        expected[spec.alarm_variable] = (
            alarm_source >= threshold
            if spec.alarm_operator == ">="
            else alarm_source <= threshold
        )
        actual = compiler.execute(state, action=action, external_input=external)
        for variable in spec.variables:
            if variable.kind == "bool":
                assert actual[variable.name] is expected[variable.name]
            else:
                assert actual[variable.name] == pytest.approx(expected[variable.name], abs=1e-12)
        symbols, constraints = compiler.z3_step(
            state, action=action, external_input=external, prefix=f"eq_{index}"
        )
        solver = Solver()
        solver.add(*constraints)
        assert solver.check() == sat
        model = solver.model()
        for variable in spec.variables:
            if variable.kind == "bool":
                assert bool(model.eval(symbols[variable.name])) is actual[variable.name]
            else:
                value = float(model.eval(symbols[variable.name]).as_decimal(30).rstrip("?"))
                assert value == pytest.approx(actual[variable.name], abs=1e-12)


def test_ir_hash_is_canonical_and_contracts_are_immutable():
    first = thermal_spec()
    assert first.sha256 == thermal_spec().sha256
    with pytest.raises(TypeError):
        first.parameters["cooling_effect"] = 9.0


def test_planner_is_deterministic_and_reports_full_horizon():
    planner = SMTPlanner(TransitionCompiler(deferred_load_spec()))
    state = {"load": 0.70, "debt": 0.0, "boosting": False, "alarm": False}
    first = planner.plan(state, external_input=0.03)
    assert first == planner.plan(state, external_input=0.03)
    assert first.status == "sat"
    assert first.actions and first.projected_states and first.constraint_ids
    assert first.tie_breaks == ("objective", "length", "actions")


def test_jtms_retracts_transitively_but_preserves_alternative_support():
    ledger = TemporalAssumptionLedger()
    for name in ("a", "b", "c", "d"):
        ledger.add_belief(belief_id=name, proposition=name, confidence=1.0, logical_time=1)
    ledger.justify(Justification("j1", ("a",), "c", "rule"))
    ledger.justify(Justification("j2", ("b",), "c", "rule"))
    ledger.justify(Justification("j3", ("c",), "d", "rule"))
    assert ledger.contradict("a")["out"] == ("a",)
    assert {item.belief_id: item.status for item in ledger.beliefs}["c"] == "IN"
    revision = ledger.contradict("b")
    assert "c" in revision["revisable"] and "d" in revision["revisable"]


def test_causal_overlay_promotes_and_rolls_back():
    base = thermal_spec(cooling_effect=0.07)
    learner = CausalLearningEngine(base)
    state = {"temperature": 0.8, "cooling_active": False, "alarm": False}
    promoted = None
    for _ in range(16):
        predicted = TransitionCompiler(learner.active_spec).execute(
            state, action="activate_cooling", external_input=0.0
        )
        observed = dict(predicted)
        observed["temperature"] = 0.8 - 0.105
        promoted = learner.observe(
            TransitionEvidence(state, "activate_cooling", 0.0, observed, predicted)
        ) or promoted
    assert promoted is not None
    assert promoted.parameter_updates["cooling_effect"] == pytest.approx(0.105)
    for _ in range(8):
        predicted = TransitionCompiler(learner.active_spec).execute(
            state, action="activate_cooling", external_input=0.0
        )
        observed = TransitionCompiler(base).execute(
            state, action="activate_cooling", external_input=0.0
        )
        learner.observe(TransitionEvidence(state, "activate_cooling", 0.0, observed, predicted))
    assert learner.active_overlay is None
    assert learner.last_event and learner.last_event["kind"] == "rollback"


def test_self_model_abstains_then_commits():
    model = IncrementalSelfModel()
    spec = thermal_spec()
    initial = model.predict(
        spec=spec, regime="alarm", action="activate_cooling", plan_length=1, risk=0.0
    )
    assert initial.decision == "abstain"
    for _ in range(4):
        model.observe(initial.signature, success=True, cost=1.0)
    learned = model.predict(
        spec=spec, regime="alarm", action="activate_cooling", plan_length=1, risk=0.0
    )
    assert learned.decision == "commit" and learned.success_probability >= 0.60


def test_runtime_does_not_learn_self_outcome_when_guard_keeps_baseline():
    runtime = MCIRuntime(deferred_load_spec(shed_effect=0.05, shed_debt=0.02))
    state = {"load": 0.7, "debt": 0.0, "boosting": False, "alarm": False}
    proposal = runtime.propose(state=state, external_input=0.03, logical_time=1, regime="test")
    assert proposal["mci_first_action"] == "shed_load"
    observed = TransitionCompiler(runtime.base_spec).execute(
        state, action="boost_throughput", external_input=0.03
    )
    outcome = runtime.observe_outcome(
        observed, committed_action="boost_throughput", logical_time=2, reasoning_cost=1.0
    )
    assert outcome["prediction_error"] == 0.0
    assert outcome["recommendation_committed"] is False
