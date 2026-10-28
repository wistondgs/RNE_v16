"""Metricas reproducibles de promocion global bajo A-M0."""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Sequence

from .contracts import OrganismImpactReport, OrganismImpactVector


@dataclass(frozen=True, slots=True)
class ImpactObservation:
    seed: int
    baseline_primary: float
    candidate_primary: float
    baseline: OrganismImpactVector
    candidate: OrganismImpactVector


def expected_calibration_error(
    confidences: Sequence[float],
    outcomes: Sequence[bool],
    *,
    bins: int = 10,
) -> float:
    if len(confidences) != len(outcomes) or not confidences:
        raise ValueError("ece_requires_equal_non_empty_sequences")
    if bins <= 0:
        raise ValueError("ece_bins_must_be_positive")
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for confidence, outcome in zip(confidences, outcomes):
        value = min(max(float(confidence), 0.0), 1.0)
        index = min(int(value * bins), bins - 1)
        buckets[index].append((value, bool(outcome)))
    total = len(confidences)
    return sum(
        (len(bucket) / total)
        * abs(fmean(item[0] for item in bucket) - fmean(float(item[1]) for item in bucket))
        for bucket in buckets
        if bucket
    )


def build_impact_report(
    *,
    organ: str,
    model_id: str,
    observations: Iterable[ImpactObservation],
    ece: float | None = None,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 0,
) -> OrganismImpactReport:
    rows = list(observations)
    if not rows:
        raise ValueError("impact_report_requires_observations")
    deltas = [row.candidate_primary - row.baseline_primary for row in rows]
    low, high = _bootstrap_ci(
        deltas,
        samples=max(int(bootstrap_samples), 200),
        seed=bootstrap_seed,
    )
    return OrganismImpactReport(
        organ=organ,
        model_id=model_id,
        seeds=tuple(sorted({row.seed for row in rows})),
        baseline=_average_vector([row.baseline for row in rows]),
        candidate=_average_vector([row.candidate for row in rows]),
        primary_metric_delta=fmean(deltas),
        primary_metric_ci95=(low, high),
        ece=ece,
    )


def _bootstrap_ci(values: Sequence[float], *, samples: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(
        fmean(values[rng.randrange(len(values))] for _ in values)
        for _ in range(samples)
    )
    low_index = max(0, int(0.025 * (len(means) - 1)))
    high_index = min(len(means) - 1, int(0.975 * (len(means) - 1)))
    return means[low_index], means[high_index]


def _average_vector(values: Sequence[OrganismImpactVector]) -> OrganismImpactVector:
    return OrganismImpactVector(
        closure_rate=fmean(item.closure_rate for item in values),
        certification_rate=fmean(item.certification_rate for item in values),
        continuity=fmean(item.continuity for item in values),
        viability=fmean(item.viability for item in values),
        latency_ms=fmean(item.latency_ms for item in values),
        cpu_pressure=fmean(item.cpu_pressure for item in values),
        memory_pressure=fmean(item.memory_pressure for item in values),
        vram_gb=fmean(item.vram_gb for item in values),
        thermal_pressure=fmean(item.thermal_pressure for item in values),
        safety_violations=sum(item.safety_violations for item in values),
    )
