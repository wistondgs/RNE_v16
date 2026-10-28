"""Tests del override determinista guardado (actuación del razonamiento en conflicto)."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.storage import StorageConfig, StorageFactory
from runtime.world import ScenarioEpisodeRunner
from runtime.world.grid_thermal_scenario import GridThermalScenario
from runtime.world.intervention_override import (
    OverrideDecision,
    detect_structural_conflict,
    evaluate_override,
    family_recommendations,
    guard_candidate,
    is_actuation_enabled,
)

CONFLICT = dict(
    grid_size=5,
    topology="uniform",
    initial_temperature=0.88,
    alarm_threshold=0.85,
    cooling_effect=0.07,
)


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "ov.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "art",
        prefer_postgres_reads=False,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


def _run(tmp_path, *, profile, actuate, regime="causal_counterfactual_conflict", monkeypatch):
    monkeypatch.setenv("RNFE_REASONING_MODE", "adaptive")
    monkeypatch.setenv("RNFE_REASONING_FAMILY_PROFILE", profile)
    monkeypatch.setenv("RNFE_REASONING_REGIME_HINT", regime)
    monkeypatch.setenv("RNFE_REASONING_MAX_STEPS", "10")
    if actuate:
        monkeypatch.setenv("RNFE_REASONING_ACTUATES", "1")
    else:
        monkeypatch.delenv("RNFE_REASONING_ACTUATES", raising=False)
    runner = ScenarioEpisodeRunner(
        scenario=GridThermalScenario(**CONFLICT),
        storage=_storage(tmp_path),
        run_id="ov",
        closure_profile="adaptive_min",
    )
    return runner.run_episode(external_input=0.04)


class TestPureLogic:
    def test_conflict_detected_from_helps_goal(self):
        assert detect_structural_conflict({"cau_link": {"helps_goal": False}}) is True
        assert detect_structural_conflict({"ctf_checked": {"agreement_with_relation_kind": False}}) is True
        assert detect_structural_conflict({"cau_link": {"helps_goal": True}}) is False
        assert detect_structural_conflict({}) is False

    def test_family_recommendations_normalized_and_ordered(self):
        state = {"opt_intervention": "ACTIVATE_COOLING", "plan_first_action": "activate_cooling"}
        recs = family_recommendations(state, ["activate_cooling", "deactivate_cooling"])
        assert recs[0] == ("opt", "activate_cooling")
        assert ("plan", "activate_cooling") in recs

    def test_guard_accepts_only_strict_improvement(self):
        # minimize: menor valor es mejor.
        ok, reason, gain = guard_candidate(direction="minimize", factual_value=0.88, candidate_value=0.81)
        assert ok is True and gain > 0
        ok2, reason2, _ = guard_candidate(direction="minimize", factual_value=0.81, candidate_value=0.88)
        assert ok2 is False and reason2 == "no_improvement"

    def test_evaluate_fires_with_conflict_recommendation_and_guard(self):
        state = {"cau_link": {"helps_goal": False}, "opt_intervention": "activate_cooling"}
        values = {"activate_cooling": 0.81, "deactivate_cooling": 0.88}
        decision = evaluate_override(
            reasoning_state=state,
            allowed_interventions=["activate_cooling", "deactivate_cooling"],
            greedy_intervention="deactivate_cooling",
            direction="minimize",
            factual_value=0.88,
            simulate_value=lambda iv: values[iv],
        )
        assert decision.fired is True
        assert decision.driver_family == "opt"
        assert decision.to_intervention == "activate_cooling"

    def test_evaluate_no_fire_without_conflict(self):
        decision = evaluate_override(
            reasoning_state={"opt_intervention": "activate_cooling"},
            allowed_interventions=["activate_cooling", "deactivate_cooling"],
            greedy_intervention="deactivate_cooling",
            direction="minimize",
            factual_value=0.88,
            simulate_value=lambda iv: 0.81,
        )
        assert decision.fired is False and decision.guard_reason == "no_conflict"

    def test_evaluate_no_fire_without_recommendation(self):
        decision = evaluate_override(
            reasoning_state={"cau_link": {"helps_goal": False}},  # conflicto, sin rec
            allowed_interventions=["activate_cooling", "deactivate_cooling"],
            greedy_intervention="deactivate_cooling",
            direction="minimize",
            factual_value=0.88,
            simulate_value=lambda iv: 0.81,
        )
        assert decision.fired is False and decision.guard_reason == "no_family_recommendation"

    def test_guard_rejects_when_candidate_worse(self):
        # Familia recomienda la alterna pero NO mejora ⇒ no override.
        state = {"cau_link": {"helps_goal": False}, "opt_intervention": "activate_cooling"}
        decision = evaluate_override(
            reasoning_state=state,
            allowed_interventions=["activate_cooling", "deactivate_cooling"],
            greedy_intervention="deactivate_cooling",
            direction="minimize",
            factual_value=0.81,
            simulate_value=lambda iv: 0.90,  # alterna peor
        )
        assert decision.fired is False and decision.guard_reason == "no_improvement"


class TestShadowDiscipline:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RNFE_REASONING_ACTUATES", raising=False)
        assert is_actuation_enabled() is False

    def test_flag_off_no_override(self, tmp_path, monkeypatch):
        result = _run(tmp_path, profile="core_plus_opt", actuate=False, monkeypatch=monkeypatch)
        assert result["intervention_override"]["fired"] is False
        assert result["intervention_override"]["guard_reason"] == "actuation_disabled"
        # Camino nominal: greedy aplica deactivate_cooling.
        assert result["episode"]["context"]["intervention"] == "deactivate_cooling"


class TestLiveConflictResolution:
    def test_core_only_does_not_override_and_stays_greedy(self, tmp_path, monkeypatch):
        # Sin familia deliberativa que recomiende la alterna ⇒ no override (baseline honesto).
        result = _run(tmp_path, profile="core_only", actuate=True, monkeypatch=monkeypatch)
        ov = result["intervention_override"]
        assert ov["fired"] is False
        assert ov["guard_reason"] == "no_family_recommendation"
        assert result["episode"]["context"]["intervention"] == "deactivate_cooling"

    @pytest.mark.parametrize("profile,driver", [
        ("core_plus_opt", "opt"),
        ("core_plus_plan", "plan"),
        ("core_plus_ind", "ind"),
    ])
    def test_deliberative_family_resolves_conflict(self, tmp_path, monkeypatch, profile, driver):
        result = _run(tmp_path, profile=profile, actuate=True, monkeypatch=monkeypatch)
        ov = result["intervention_override"]
        assert ov["fired"] is True
        assert ov["driver_family"] == driver
        assert ov["to_intervention"] == "activate_cooling"
        assert ov["margin_gain"] > 0
        # La acción aplicada cambió a la correcta ⇒ temperatura bajo alarma.
        assert result["episode"]["context"]["intervention"] == "activate_cooling"
        temp = result["episode"]["result"]["updated_world"]["global_temp_mean"]
        assert temp < CONFLICT["alarm_threshold"]

class TestEffectivenessReward:
    def test_effectiveness_term_off_by_default(self, tmp_path, monkeypatch):
        from runtime.reasoning.scheduler_meta.reward import compute_episode_reward

        block = compute_episode_reward(
            delta_ioc=0.0, reasoning_cost=6.0, cost_budget=10.0, effectiveness=0.5
        )
        assert block["lambda_effectiveness"] == 0.0
        assert block["effectiveness_term"] == 0.0  # sombra: no afecta r

    def test_effectiveness_term_rewards_world_success(self):
        from runtime.reasoning.scheduler_meta.reward import compute_episode_reward

        fail = compute_episode_reward(
            delta_ioc=0.0, reasoning_cost=6.0, cost_budget=10.0,
            effectiveness=-0.03, lambda_effectiveness=0.5,
        )
        win = compute_episode_reward(
            delta_ioc=0.0, reasoning_cost=6.0, cost_budget=10.0,
            effectiveness=0.04, lambda_effectiveness=0.5,
        )
        # La acción efectiva (mundo seguro) recibe más recompensa que la fallida.
        assert win["reward"] > fail["reward"]
        assert win["effectiveness_term"] > 0 and fail["effectiveness_term"] < 0

    def test_outcome_effectiveness_signs(self):
        from runtime.world.intervention_override import outcome_effectiveness

        # threshold_above (térmico): seguro cuando value < umbral.
        assert outcome_effectiveness(value=0.81, alarm_threshold=0.85, alarm_semantics="threshold_above") > 0
        assert outcome_effectiveness(value=0.88, alarm_threshold=0.85, alarm_semantics="threshold_above") < 0
        # threshold_below (recurso): seguro cuando value > umbral.
        assert outcome_effectiveness(value=0.30, alarm_threshold=0.20, alarm_semantics="threshold_below") > 0

    def test_conflict_resolution_flips_reward_sign(self, tmp_path, monkeypatch):
        # Con efectividad activa, resolver el conflicto (override) da r mayor que el greedy.
        monkeypatch.setenv("RNFE_REWARD_LAMBDA_EFFECTIVENESS", "0.5")
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)
        r_core = _run(tmp_path / "a", profile="core_only", actuate=True, monkeypatch=monkeypatch)
        r_opt = _run(tmp_path / "b", profile="core_plus_opt", actuate=True, monkeypatch=monkeypatch)
        assert r_opt["reasoning_reward"]["reward"] > r_core["reasoning_reward"]["reward"]

    def test_override_emits_audit_event(self, tmp_path, monkeypatch):
        storage = _storage(tmp_path)
        monkeypatch.setenv("RNFE_REASONING_MODE", "adaptive")
        monkeypatch.setenv("RNFE_REASONING_FAMILY_PROFILE", "core_plus_opt")
        monkeypatch.setenv("RNFE_REASONING_REGIME_HINT", "causal_counterfactual_conflict")
        monkeypatch.setenv("RNFE_REASONING_MAX_STEPS", "10")
        monkeypatch.setenv("RNFE_REASONING_ACTUATES", "1")
        runner = ScenarioEpisodeRunner(
            scenario=GridThermalScenario(**CONFLICT),
            storage=storage,
            run_id="ov-audit",
            closure_profile="adaptive_min",
        )
        runner.run_episode(external_input=0.04)
        events = [e.event_type for e in storage.list_events(run_id="ov-audit", limit=200)]
        assert "reasoning.intervention_override" in events
