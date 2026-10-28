"""Tests para TransferAssessment y assess_transfer()."""

from runtime.certification.transfer_assessment import (
    TransferAssessment,
    assess_transfer,
)
from runtime.world.compatibility import (
    CompatibilityAssessment,
    ScenarioCompatibilityGraph,
)
from runtime.world.thermal_scenario import ThermalScenario
from runtime.world.resource_scenario import ResourceScenario
from runtime.reality.transition_analysis import (
    TransitionContinuityVector,
    compute_transition_vector,
)


_SEQUENCE = ["ABD", "ANA", "CAU", "CTF", "DED", "PROB"]


def _trace(families=_SEQUENCE):
    """Traza con la forma real de `ReasoningTraceStep.__dict__` (meta_scheduler).

    B1: antes estos fixtures no traían traza y `trace_integrity` daba True igual
    (era tautológico). Ahora se verifica de verdad, así que un episodio completo
    tiene que traer su traza para representar lo que estos tests dicen medir.
    """
    return [
        {"family": f, "status": "ok", "detail": {}, "timestamp": 1000.0 + i}
        for i, f in enumerate(families)
    ]


def _make_episode(
    scenario_name, main_var, main_val, alarm, props, intervention,
    rk="support", cross_memory=False,
):
    mem = []
    if cross_memory:
        mem = [{"analogical_source": True, "retrieval_metrics": {
            "retrieved_same_scenario_count": 1,
            "retrieved_cross_scenario_count": 2,
        }}]
    return {
        "episode": {
            "trace": _trace(),
            "episode_id": f"ep-{scenario_name}",
            "scenario": scenario_name,
            "scenario_metadata": {"scenario_name": scenario_name, "main_variable": main_var},
            "closure_profile": "adaptive_min",
            "context": {
                "observation": {main_var: main_val, "alarm": alarm, "propositions": props},
                "intervention": intervention,
                "counterfactual": {main_var: main_val + 0.05},
                "retrieved_memory": mem,
            },
            "result": {
                "updated_world": {main_var: main_val - 0.03},
                "relation_kind": rk,
                "reasoning_sequence": list(_SEQUENCE),
            },
        },
    }


class TestTransferAssessment:
    def test_local_no_transfer(self):
        """Episodio local sin cross-scenario = certified_local."""
        ep = _make_episode(
            "thermal_homeostasis", "temperature", 0.88, True,
            ["TEMP_HIGH"], "activate_cooling",
        )
        result = assess_transfer(episode_result=ep)
        assert isinstance(result, TransferAssessment)
        assert result.transfer_verdict == "certified_local"
        assert result.cross_scenario_evidence_used is False
        assert result.memory_purity_score == 1.0

    def test_compatible_clean_is_transfer_safe(self):
        """compatible + clean + stable + history = certified_transfer_safe.

        RTCME-v2: With Bayesian posterior, achieving compatible_transfer scope
        requires strong evidence. Historical success data helps meet the
        LCB threshold.
        """
        compat = CompatibilityAssessment(
            source_scenario="thermal_homeostasis",
            target_scenario="thermal_v2",
            compatibility_class="compatible",
            topology_score=0.9,
            objective_score=0.9,
            intervention_score=0.8,
            counterfactual_score=0.8,
            overall_score=0.87,
            penalty_multiplier=0.85,
            transfer_allowed=True,
            certification_allowed=True,
        )
        vector = TransitionContinuityVector(
            source_scenario="thermal_homeostasis",
            target_scenario="thermal_v2",
            semantic_retention=0.8,
            trace_stability=0.9,
            causal_stability=1.0,
            intervention_policy_stability=0.9,
            structural_compatibility=0.87,
            memory_purity=0.98,
            composite_score=0.85,
            transition_type="compatible",
        )
        ep = _make_episode(
            "thermal_homeostasis", "temperature", 0.88, True,
            ["TEMP_HIGH"], "activate_cooling",
        )
        result = assess_transfer(
            episode_result=ep,
            compatibility=compat,
            transition_vector=vector,
            historical_success_rate=0.90,
            n_historical=15,
        )
        # With Bayesian posterior: compatible + strong evidence + history
        assert result.transfer_verdict in ("certified_transfer_safe", "certified_analogical_only")
        assert result.certificate_scope in ("compatible_transfer", "analogical_hint_only")

    def test_analogical_marked(self):
        """Evidencia analógica = certified_analogical_only."""
        graph = ScenarioCompatibilityGraph()
        tp = ThermalScenario().structural_profile
        rp = ResourceScenario().structural_profile
        compat = graph.assess(tp, rp)
        vector = TransitionContinuityVector(
            source_scenario="thermal_homeostasis",
            target_scenario="resource_management",
            semantic_retention=0.2,
            trace_stability=0.8,
            causal_stability=0.7,
            intervention_policy_stability=0.5,
            structural_compatibility=compat.overall_score,
            memory_purity=0.9,
            composite_score=0.55,
            transition_type="analogical",
        )
        ep = _make_episode(
            "thermal_homeostasis", "temperature", 0.88, True,
            ["TEMP_HIGH"], "activate_cooling", cross_memory=True,
        )
        result = assess_transfer(
            episode_result=ep,
            compatibility=compat,
            transition_vector=vector,
        )
        assert result.transfer_verdict == "certified_analogical_only"
        assert result.analogical_source_present is True

    def test_contaminated_strict_rejected(self):
        """Contaminación con incompatible = rejected_for_transfer."""
        compat = CompatibilityAssessment(
            source_scenario="thermal_homeostasis",
            target_scenario="incompatible",
            compatibility_class="incompatible",
            topology_score=0.2,
            objective_score=0.3,
            intervention_score=0.1,
            counterfactual_score=0.2,
            overall_score=0.20,
            penalty_multiplier=0.0,
            transfer_allowed=False,
            certification_allowed=False,
        )
        vector = TransitionContinuityVector(
            source_scenario="thermal_homeostasis",
            target_scenario="incompatible",
            semantic_retention=0.1,
            trace_stability=0.3,
            causal_stability=0.0,
            intervention_policy_stability=0.2,
            structural_compatibility=0.20,
            memory_purity=0.3,
            composite_score=0.18,
            transition_type="incompatible",
        )
        ep = _make_episode(
            "thermal_homeostasis", "temperature", 0.88, True,
            ["TEMP_HIGH"], "activate_cooling",
        )
        result = assess_transfer(
            episode_result=ep,
            compatibility=compat,
            transition_vector=vector,
        )
        assert result.transfer_verdict == "rejected_for_transfer"

    def test_fields_populated(self):
        ep = _make_episode(
            "thermal_homeostasis", "temperature", 0.88, True,
            ["TEMP_HIGH"], "activate_cooling",
        )
        result = assess_transfer(episode_result=ep)
        assert result.episode_id == "ep-thermal_homeostasis"
        assert result.source_scenario == "thermal_homeostasis"
        assert result.closure_profile == "adaptive_min"
