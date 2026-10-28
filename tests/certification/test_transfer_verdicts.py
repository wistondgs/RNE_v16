"""Tests para verdicts de transferencia en distintos escenarios."""

from runtime.certification.transfer_assessment import (
    TransferAssessment,
    assess_transfer,
)
from runtime.reality.transition_analysis import TransitionContinuityVector
from runtime.world.compatibility import CompatibilityAssessment


_SEQUENCE = ["ABD", "ANA", "CAU", "CTF", "DED", "PROB"]


def _trace(families=_SEQUENCE):
    """Traza con la forma real de `ReasoningTraceStep.__dict__` (B1).

    Sin traza, `trace_integrity` ahora es False (antes: True tautológico), así
    que un episodio "completo" debe traerla para representar lo que se mide acá.
    """
    return [
        {"family": f, "status": "ok", "detail": {}, "timestamp": 1000.0 + i}
        for i, f in enumerate(families)
    ]


def _ep(scenario="thermal_homeostasis", cross_mem=False):
    mem = []
    if cross_mem:
        mem = [{"analogical_source": True, "retrieval_metrics": {
            "retrieved_same_scenario_count": 1,
            "retrieved_cross_scenario_count": 1,
        }}]
    return {
        "episode": {
            "trace": _trace(),
            "episode_id": f"ep-{scenario}",
            "scenario": scenario,
            "scenario_metadata": {"scenario_name": scenario, "main_variable": "temperature"},
            "closure_profile": "baseline_fixed",
            "context": {
                "observation": {"temperature": 0.88, "alarm": True, "propositions": ["TEMP_HIGH"]},
                "intervention": "activate_cooling",
                "counterfactual": {"temperature": 0.92},
                "retrieved_memory": mem,
            },
            "result": {
                "updated_world": {"temperature": 0.83},
                "relation_kind": "support",
                "reasoning_sequence": list(_SEQUENCE),
            },
        },
    }


def _compat(cls, src="thermal_homeostasis", tgt="thermal_homeostasis", score=1.0):
    return CompatibilityAssessment(
        source_scenario=src,
        target_scenario=tgt,
        compatibility_class=cls,
        topology_score=1.0,
        objective_score=1.0,
        intervention_score=1.0,
        counterfactual_score=1.0,
        overall_score=score,
        penalty_multiplier=1.0,
        transfer_allowed=cls != "incompatible",
        certification_allowed=cls in ("equivalent", "compatible"),
    )


def _vec(purity=1.0, composite=0.85, ttype="intra"):
    return TransitionContinuityVector(
        source_scenario="thermal_homeostasis",
        target_scenario="thermal_homeostasis",
        semantic_retention=0.9,
        trace_stability=0.9,
        causal_stability=1.0,
        intervention_policy_stability=0.9,
        structural_compatibility=0.95,
        memory_purity=purity,
        composite_score=composite,
        transition_type=ttype,
    )


class TestTransferVerdicts:
    """Verifica cada posible verdict.

    RTCME-v2: Verdicts are now determined by Bayesian posterior,
    not by fixed thresholds. Tests adapted accordingly.
    """

    def test_certified_local_when_equivalent_no_cross(self):
        result = assess_transfer(
            episode_result=_ep(),
            compatibility=_compat("equivalent"),
            transition_vector=_vec(),
        )
        assert result.transfer_verdict == "certified_local"

    def test_certified_transfer_safe_compatible_clean(self):
        """Compatible with good evidence + history → transfer safe."""
        result = assess_transfer(
            episode_result=_ep(cross_mem=True),
            compatibility=_compat("compatible", tgt="resource_management", score=0.80),
            transition_vector=_vec(purity=0.98, composite=0.90, ttype="compatible"),
            historical_success_rate=0.90,
            n_historical=15,
        )
        assert result.transfer_verdict in ("certified_transfer_safe", "certified_analogical_only")
        # Posterior-based: scope depends on LCB and morphism class
        assert result.certificate_scope in ("compatible_transfer", "analogical_hint_only")

    def test_certified_analogical_only(self):
        result = assess_transfer(
            episode_result=_ep(cross_mem=True),
            compatibility=_compat("analogical", tgt="resource_management", score=0.55),
            transition_vector=_vec(purity=0.80, composite=0.55, ttype="analogical"),
        )
        assert result.transfer_verdict == "certified_analogical_only"

    def test_rejected_incompatible(self):
        result = assess_transfer(
            episode_result=_ep(),
            compatibility=_compat("incompatible", tgt="fake", score=0.20),
            transition_vector=_vec(purity=0.40, composite=0.20, ttype="incompatible"),
        )
        assert result.transfer_verdict == "rejected_for_transfer"

    def test_rejected_low_purity(self):
        """Even compatible, if purity is very low → blocked by failure mode."""
        result = assess_transfer(
            episode_result=_ep(cross_mem=True),
            compatibility=_compat("compatible", tgt="resource_management"),
            transition_vector=_vec(purity=0.30, composite=0.80, ttype="compatible"),
        )
        assert result.transfer_verdict == "rejected_for_transfer"

    def test_rejected_low_stability(self):
        """Low stability with low purity → rejected or analogical only.

        With Bayesian posterior, low stability alone may not block
        if other evidence is strong. Combined with low scores
        it should lead to rejection.
        """
        result = assess_transfer(
            episode_result=_ep(cross_mem=True),
            compatibility=_compat("compatible", tgt="resource_management", score=0.20),
            transition_vector=_vec(purity=0.50, composite=0.15, ttype="compatible"),
        )
        assert result.transfer_verdict in ("rejected_for_transfer", "certified_analogical_only")
