"""Health y buffer acotado para trazas neuronales no silenciosas."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class BufferedTraceEvent:
    event_type: str
    payload: Mapping[str, Any]
    run_id: str | None
    source: str
    timestamp: str


@dataclass(frozen=True, slots=True)
class TraceHealthSnapshot:
    storage_configured: bool
    degraded: bool
    persistence_failures: int
    consecutive_failures: int
    pending_events: int
    dropped_events: int
    recovered_events: int
    last_error: str | None
    last_failure_at: str | None
    last_recovery_at: str | None


class TracePersistenceMonitor:
    def __init__(self, *, storage_configured: bool, max_buffered_events: int = 128):
        if max_buffered_events <= 0:
            raise ValueError("trace_buffer_size_must_be_positive")
        self.storage_configured = storage_configured
        self.max_buffered_events = int(max_buffered_events)
        self._pending: deque[BufferedTraceEvent] = deque()
        self._persistence_failures = 0
        self._consecutive_failures = 0
        self._dropped_events = 0
        self._recovered_events = 0
        self._last_error: str | None = None
        self._last_failure_at: str | None = None
        self._last_recovery_at: str | None = None
        self._lock = RLock()

    def new_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        run_id: str | None,
        source: str = "runtime.neural",
    ) -> BufferedTraceEvent:
        return BufferedTraceEvent(
            event_type=event_type,
            payload=dict(payload),
            run_id=run_id,
            source=source,
            timestamp=_utc_now_iso(),
        )

    def record_failure(self, event: BufferedTraceEvent, error: BaseException) -> None:
        with self._lock:
            self._record_error(error)
            if len(self._pending) >= self.max_buffered_events:
                self._pending.popleft()
                self._dropped_events += 1
            self._pending.append(event)

    def record_flush_failure(self, error: BaseException) -> None:
        with self._lock:
            self._record_error(error)

    def pending(self) -> tuple[BufferedTraceEvent, ...]:
        with self._lock:
            return tuple(self._pending)

    def mark_flushed(self, count: int) -> None:
        with self._lock:
            actual = min(max(int(count), 0), len(self._pending))
            for _ in range(actual):
                self._pending.popleft()
            self._recovered_events += actual
            if not self._pending:
                self._consecutive_failures = 0
                self._last_recovery_at = _utc_now_iso()

    def snapshot(self) -> TraceHealthSnapshot:
        with self._lock:
            return TraceHealthSnapshot(
                storage_configured=self.storage_configured,
                degraded=bool(self._pending or self._consecutive_failures),
                persistence_failures=self._persistence_failures,
                consecutive_failures=self._consecutive_failures,
                pending_events=len(self._pending),
                dropped_events=self._dropped_events,
                recovered_events=self._recovered_events,
                last_error=self._last_error,
                last_failure_at=self._last_failure_at,
                last_recovery_at=self._last_recovery_at,
            )

    def _record_error(self, error: BaseException) -> None:
        self._persistence_failures += 1
        self._consecutive_failures += 1
        self._last_error = f"{error.__class__.__name__}:{str(error)[:200]}"
        self._last_failure_at = _utc_now_iso()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
