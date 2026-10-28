from runtime.neural import (
    ImpactObservation,
    OrganismImpactVector,
    build_impact_report,
    expected_calibration_error,
)


def _vector(*, closure=0.9, safety=0):
    return OrganismImpactVector(
        closure_rate=closure,
        certification_rate=0.9,
        continuity=0.8,
        viability=0.8,
        latency_ms=10,
        cpu_pressure=0.2,
        memory_pressure=0.2,
        vram_gb=0.5,
        thermal_pressure=0.1,
        safety_violations=safety,
    )


def test_a_m0_benchmark_uses_reproducible_ci_and_global_vector() -> None:
    observations = [
        ImpactObservation(seed=seed, baseline_primary=0.5, candidate_primary=0.6, baseline=_vector(), candidate=_vector(closure=0.895))
        for seed in (1, 2, 3, 4)
    ]
    report = build_impact_report(
        organ="N1",
        model_id="router-v1",
        observations=observations,
        ece=0.05,
        bootstrap_seed=17,
    )
    assert report.primary_metric_ci95[0] > 0.0
    assert report.promotion_eligible() is True


def test_ece_is_zero_for_perfect_binary_confidence() -> None:
    assert expected_calibration_error([0.0, 1.0], [False, True], bins=2) == 0.0
