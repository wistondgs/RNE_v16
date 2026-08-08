"""Detector determinista de cambio de régimen por error predictivo sostenido."""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeChangeDetected:
    logical_time: int
    prediction_error: float
    threshold: float
    consecutive_anomalies: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "logical_time": self.logical_time,
            "prediction_error": self.prediction_error,
            "threshold": self.threshold,
            "consecutive_anomalies": self.consecutive_anomalies,
        }


class RegimeDetector:
    def __init__(self, *, window: int = 16, consecutive_required: int = 3):
        self._errors: deque[float] = deque(maxlen=max(4, int(window)))
        self.consecutive_required = max(2, int(consecutive_required))
        self._consecutive = 0
        self._latched = False
        self.last_event: RegimeChangeDetected | None = None

    def check(self, prediction_error: float, *, logical_time: int = 0) -> bool:
        error = abs(float(prediction_error))
        history = list(self._errors)
        median = statistics.median(history) if history else 0.0
        mad = (
            statistics.median(abs(item - median) for item in history)
            if history
            else 0.0
        )
        threshold = max(1e-6, median + 2.0 * mad)
        anomalous = len(history) >= 4 and error > threshold
        self._errors.append(error)
        if anomalous:
            self._consecutive += 1
        else:
            self._consecutive = 0
            self._latched = False
        if self._consecutive < self.consecutive_required or self._latched:
            return False
        self._latched = True
        self.last_event = RegimeChangeDetected(
            logical_time=int(logical_time),
            prediction_error=round(error, 9),
            threshold=round(threshold, 9),
            consecutive_anomalies=self._consecutive,
        )
        return True
