from __future__ import annotations

from runtime.symbolic.mci import RegimeDetector
from runtime.symbolic.mci.causal_learning import (
    CausalLearningEngine,
    TransitionEvidence,
)
from runtime.symbolic.mci.compiler import TransitionCompiler
from runtime.symbolic.mci.jtms import TemporalAssumptionLedger
from runtime.symbolic.mci.specs import thermal_spec


def test_regime_change_segments_learning_and_retracts_old_belief():
    base = thermal_spec(cooling_effect=0.07)
    changed = thermal_spec(cooling_effect=0.14)
    learner = CausalLearningEngine(base)
    detector = RegimeDetector(window=16, consecutive_required=3)
    ledger = TemporalAssumptionLedger()
    old = ledger.add_belief(
        belief_id="cooling/coefficient/old",
        proposition="cooling_effect=0.07",
        confidence=1.0,
        logical_time=1,
    )
    detected_episode = None
    adjusted_episode = None

    for episode in range(60):
        state = {
            "temperature": 0.9,
            "cooling_active": False,
            "alarm": True,
        }
        predicted = TransitionCompiler(learner.active_spec).execute(
            state, action="activate_cooling", external_input=0.0
        )
        actual_spec = base if episode < 30 else changed
        observed = TransitionCompiler(actual_spec).execute(
            state, action="activate_cooling", external_input=0.0
        )
        error = observed["temperature"] - predicted["temperature"]
        if detector.check(error, logical_time=episode * 2 + 2):
            detected_episode = episode
            learner.segment_regime(logical_time=episode * 2 + 2)
            stale = ledger.mark_empirically_stale(
                before_logical_time=episode * 2 + 2
            )
            assert old.belief_id in stale
        overlay = learner.observe(
            TransitionEvidence(
                state=state,
                action="activate_cooling",
                external_input=0.0,
                observed=observed,
                predicted=predicted,
            )
        )
        if (
            overlay is not None
            and abs(
                float(learner.active_spec.parameters["cooling_effect"]) - 0.14
            )
            < 0.02
        ):
            adjusted_episode = episode
            ledger.resolve_empirical_stale(old.belief_id, confirmed=False)
            break

    assert detected_episode is not None
    assert detected_episode - 30 < 10
    assert adjusted_episode is not None
    assert adjusted_episode - detected_episode < 20
    beliefs = {belief.belief_id: belief for belief in ledger.beliefs}
    assert beliefs[old.belief_id].status == "OUT"
    assert learner.archived_regimes
