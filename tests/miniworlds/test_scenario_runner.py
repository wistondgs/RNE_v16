"""Tests para escenarios cognitivos parametrizables."""

from pathlib import Path

import pytest

from runtime.storage import StorageConfig, StorageFactory
from runtime.world import (
    CognitiveScenario,
    ThermalScenario,
    ResourceScenario,
    ScenarioEpisodeRunner,
    get_scenario,
    list_scenarios,
    SCENARIO_REGISTRY,
    DEFAULT_SCENARIO,
)


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "scenario.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=True,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


class TestScenarioRegistry:
    """Tests para el registro de escenarios."""

    def test_thermal_scenario_is_registered(self):
        """Escenario térmico está registrado."""
        assert "thermal_homeostasis" in SCENARIO_REGISTRY

    def test_resource_scenario_is_registered(self):
        """Escenario de recursos está registrado."""
        assert "resource_management" in SCENARIO_REGISTRY

    def test_default_scenario_is_thermal(self):
        """El escenario por defecto es thermal_homeostasis."""
        assert DEFAULT_SCENARIO == "thermal_homeostasis"

    def test_get_scenario_returns_instance(self):
        """get_scenario retorna instancia del escenario."""
        scenario = get_scenario("thermal_homeostasis")
        assert isinstance(scenario, CognitiveScenario)
        assert isinstance(scenario, ThermalScenario)

    def test_get_scenario_with_kwargs(self):
        """get_scenario acepta kwargs de configuración."""
        scenario = get_scenario("thermal_homeostasis", initial_temperature=0.9)
        obs = scenario.observe()
        assert obs.state["temperature"] == 0.9

    def test_get_scenario_raises_for_unknown(self):
        """get_scenario lanza error para escenario desconocido."""
        with pytest.raises(ValueError, match="no encontrado"):
            get_scenario("unknown_scenario")

    def test_list_scenarios_returns_configs(self):
        """list_scenarios retorna configuraciones."""
        configs = list_scenarios()
        assert "thermal_homeostasis" in configs
        assert "resource_management" in configs
        assert configs["thermal_homeostasis"].main_variable == "temperature"
        assert configs["resource_management"].main_variable == "stock_level"


class TestThermalScenario:
    """Tests para el escenario térmico."""

    def test_observe_returns_observation(self):
        """observe() retorna ScenarioObservation."""
        scenario = ThermalScenario()
        obs = scenario.observe()
        assert "temperature" in obs.state
        assert isinstance(obs.propositions, list)

    def test_factual_transition_updates_state(self):
        """factual_transition() actualiza estado."""
        scenario = ThermalScenario(initial_temperature=0.9)
        obs_before = scenario.observe()
        result = scenario.factual_transition(intervention="activate_cooling", external_input=0.03)
        obs_after = scenario.observe()

        assert result.state["cooling_active"] is True
        assert obs_after.state["temperature"] < obs_before.state["temperature"]

    def test_counterfactual_does_not_mutate_state(self):
        """simulate_counterfactual() no muta estado."""
        scenario = ThermalScenario(initial_temperature=0.9)
        obs_before = scenario.observe()
        _ = scenario.simulate_counterfactual(intervention="activate_cooling", external_input=0.03)
        obs_after = scenario.observe()

        assert obs_before.state["temperature"] == obs_after.state["temperature"]

    def test_get_formula_returns_template(self):
        """get_formula() retorna plantilla LOTF."""
        scenario = ThermalScenario()
        obs = scenario.observe()
        formula = scenario.get_formula(obs)
        assert "TEMP_HIGH" in formula
        assert "ACTIVATE_COOLING" in formula

    def test_evaluate_relation_kind_support(self):
        """evaluate_relation_kind() retorna support cuando factual es mejor."""
        scenario = ThermalScenario(initial_temperature=0.9)
        factual = scenario.factual_transition(intervention="activate_cooling", external_input=0.03)

        scenario2 = ThermalScenario(initial_temperature=0.9)
        counterfactual = scenario2.simulate_counterfactual(
            intervention="deactivate_cooling", external_input=0.03
        )

        kind = scenario.evaluate_relation_kind(factual=factual, counterfactual=counterfactual)
        assert kind == "support"


class TestResourceScenario:
    """Tests para el escenario de recursos."""

    def test_observe_returns_observation(self):
        """observe() retorna ScenarioObservation."""
        scenario = ResourceScenario()
        obs = scenario.observe()
        assert "stock_level" in obs.state
        assert isinstance(obs.propositions, list)

    def test_factual_transition_updates_state(self):
        """factual_transition() actualiza estado."""
        scenario = ResourceScenario(initial_stock=0.15)
        obs_before = scenario.observe()
        result = scenario.factual_transition(intervention="start_production", external_input=0.03)
        obs_after = scenario.observe()

        assert result.state["production_active"] is True
        assert obs_after.state["stock_level"] > obs_before.state["stock_level"]

    def test_counterfactual_does_not_mutate_state(self):
        """simulate_counterfactual() no muta estado."""
        scenario = ResourceScenario(initial_stock=0.15)
        obs_before = scenario.observe()
        _ = scenario.simulate_counterfactual(intervention="start_production", external_input=0.03)
        obs_after = scenario.observe()

        assert obs_before.state["stock_level"] == obs_after.state["stock_level"]

    def test_inverse_causality_to_thermal(self):
        """Recursos tiene causalidad inversa al térmico (LOW -> ACTIVATE)."""
        scenario = ResourceScenario(initial_stock=0.15, scarcity_threshold=0.20)
        obs = scenario.observe()

        # En escasez, debe activar producción
        assert obs.alarm is True
        intervention = scenario.select_intervention(obs)
        assert intervention == "start_production"

    def test_evaluate_relation_kind_support_for_resources(self):
        """evaluate_relation_kind() en recursos: más stock es support."""
        scenario = ResourceScenario(initial_stock=0.15)
        factual = scenario.factual_transition(intervention="start_production", external_input=0.03)

        scenario2 = ResourceScenario(initial_stock=0.15)
        counterfactual = scenario2.simulate_counterfactual(
            intervention="stop_production", external_input=0.03
        )

        kind = scenario.evaluate_relation_kind(factual=factual, counterfactual=counterfactual)
        assert kind == "support"


class TestScenarioEpisodeRunner:
    """Tests para el runner de episodios con escenarios."""

    def test_runner_with_default_thermal_scenario(self, tmp_path: Path):
        """Runner funciona con escenario térmico por defecto."""
        storage = _storage(tmp_path)
        runner = ScenarioEpisodeRunner(storage=storage, run_id="run-thermal-default")
        result = runner.run_episode(external_input=0.05)

        assert result["episode"]["scenario"] == "thermal_homeostasis"
        assert result["episode"]["result"]["reasoning_sequence"] == [
            "ABD", "ANA", "CAU", "CTF", "DED", "PROB"
        ]
        storage.close()

    def test_experience_feature_off_creates_no_behavioral_memory(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.delenv("RNFE_EXPERIENCE", raising=False)
        storage = _storage(tmp_path)
        runner = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-experience-off",
            scenario="thermal_homeostasis",
        )

        result = runner.run_episode(external_input=0.05)

        assert runner._experience is None
        assert result.get("experience") is None
        assert result.get("episode", {}).get("experience") is None
        assert storage.retrieve_memory_records(
            run_id=runner._organism_id,
            scales=["experience"],
            limit=20,
        ) == []
        storage.close()

    def test_runner_with_resource_scenario(self, tmp_path: Path):
        """Runner funciona con escenario de recursos."""
        storage = _storage(tmp_path)
        runner = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-resource",
            scenario="resource_management",
        )
        result = runner.run_episode(external_input=0.03)

        assert result["episode"]["scenario"] == "resource_management"
        assert "stock_level" in result["episode"]["context"]["observation"]
        storage.close()

    def test_runner_with_scenario_instance(self, tmp_path: Path):
        """Runner funciona con instancia de escenario."""
        storage = _storage(tmp_path)
        scenario = ThermalScenario(initial_temperature=0.95)
        runner = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-instance",
            scenario=scenario,
        )
        result = runner.run_episode(external_input=0.02)

        assert result["episode"]["scenario"] == "thermal_homeostasis"
        storage.close()

    def test_runner_persists_events_and_artifacts(self, tmp_path: Path):
        """Runner persiste eventos y artifacts."""
        storage = _storage(tmp_path)
        runner = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-persist-test",
            scenario="thermal_homeostasis",
        )
        result = runner.run_episode(external_input=0.05)

        # Verificar evento
        events = storage.list_events(run_id="run-persist-test", limit=50)
        closed_events = [e for e in events if e.event_type == "episode.closed"]
        assert len(closed_events) >= 1

        # Verificar artifact
        artifact_path = Path(result["artifact"]["abs_path"])
        assert artifact_path.exists()

        storage.close()

    def test_runner_passes_enriched_reasoning_context(self, tmp_path: Path):
        """Scheduler recibe contexto enriquecido reusable desde ScenarioEpisodeRunner."""
        storage = _storage(tmp_path)
        runner = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-reasoning-context",
            scenario="thermal_homeostasis",
        )
        result = runner.run_episode(external_input=0.05)

        reasoning_context = result["episode"]["trace"][0]["detail"]["reasoning_context"]
        assert reasoning_context["formula"]
        assert reasoning_context["memory_hits"] == reasoning_context["retrieved_memory"]
        assert "counterfactual" in reasoning_context
        assert "updated_world" in reasoning_context
        assert "factual" in reasoning_context
        assert reasoning_context["relation_kind"] in {"support", "contradiction"}
        assert reasoning_context["scenario"] == "thermal_homeostasis"
        assert reasoning_context["scenario_metadata"]["scenario_name"] == "thermal_homeostasis"
        assert reasoning_context["reasoning_mode"] == "fixed"
        ded_step = next(step for step in result["episode"]["trace"] if step["family"] == "DED")
        assert ded_step["detail"]["artifacts"]["solver_result"] == "sat"
        assert ded_step["detail"]["artifacts"]["formula_normalized"] == "TEMP_HIGH -> ACTIVATE_COOLING"
        assert ded_step["detail"]["artifacts"]["z3_expression"]
        storage.close()

    def test_runner_second_episode_includes_prior_belief_state_in_reasoning_context(self, tmp_path: Path):
        """Segundo episodio expone belief_state previo al scheduler."""
        storage = _storage(tmp_path)
        runner = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-belief-context",
            scenario="thermal_homeostasis",
        )
        runner.run_episode(external_input=0.04)
        second = runner.run_episode(external_input=0.04)

        reasoning_context = second["episode"]["trace"][0]["detail"]["reasoning_context"]
        assert "belief_state" in reasoning_context
        assert reasoning_context["belief_state"]["scenario_name"] == "thermal_homeostasis"
        storage.close()

    def test_runner_both_scenarios_produce_valid_episodes(self, tmp_path: Path):
        """Ambos escenarios producen episodios válidos."""
        storage = _storage(tmp_path)

        # Térnico
        runner1 = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-compare-thermal",
            scenario="thermal_homeostasis",
        )
        result1 = runner1.run_episode(external_input=0.05)

        # Recursos
        runner2 = ScenarioEpisodeRunner(
            storage=storage,
            run_id="run-compare-resource",
            scenario="resource_management",
        )
        result2 = runner2.run_episode(external_input=0.03)

        # Ambos deben tener episodio cerrado con veredicto válido
        valid_verdicts = ["PASSED", "CONDITIONALLY_PASSED", "certified"]
        assert result1["certification"]["verdict"] in valid_verdicts
        assert result2["certification"]["verdict"] in valid_verdicts

        # Ambos deben tener secuencia de razonamiento
        assert len(result1["episode"]["result"]["reasoning_sequence"]) >= 6
        assert len(result2["episode"]["result"]["reasoning_sequence"]) >= 6

        storage.close()
