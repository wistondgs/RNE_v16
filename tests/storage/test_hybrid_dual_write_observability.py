"""B3: el dual-write hibrido no estricto debe LOGUEAR el error del store caido.

La resiliencia se conserva (se devuelve el resultado del store bueno) pero el
error que antes se tragaba en silencio ahora se vuelve observable via warning.
"""

from __future__ import annotations

import logging

import pytest

from runtime.storage.backends.hybrid_store import HybridStorageBackend
from runtime.storage.records import StoredEvent

HYBRID_LOGGER = "runtime.storage.backends.hybrid_store"


class _FakeStore:
    """Store minimo configurable para simular exito/fallo por metodo."""

    def __init__(self, *, name: str, fail_methods: set[str] | None = None,
                 rows: list | None = None):
        self.name = name
        self.fail_methods = fail_methods or set()
        self.rows = rows if rows is not None else []
        self.calls: list[str] = []

    def append_event(self, event: StoredEvent) -> StoredEvent:
        self.calls.append("append_event")
        if "append_event" in self.fail_methods:
            raise RuntimeError(f"{self.name} append_event boom")
        return event

    def list_events(self, **kwargs: object) -> list:
        self.calls.append("list_events")
        if "list_events" in self.fail_methods:
            raise RuntimeError(f"{self.name} list_events boom")
        return list(self.rows)


def _event(run_id: str = "run-x") -> StoredEvent:
    return StoredEvent(event_type="t", payload={"k": 1}, run_id=run_id)


def test_dual_write_logs_when_primary_fails_fallback_ok(caplog):
    good_event = _event()
    primary = _FakeStore(name="PG", fail_methods={"append_event"})
    fallback = _FakeStore(name="SQLite")
    hybrid = HybridStorageBackend(
        primary=primary, fallback=fallback, strict_dual_write=False
    )

    with caplog.at_level(logging.WARNING, logger=HYBRID_LOGGER):
        result = hybrid.append_event(good_event)

    # Resiliencia conservada: se devuelve el resultado del fallback (el bueno).
    assert result is good_event
    assert fallback.calls == ["append_event"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "append_event" in msg
    assert "primary" in msg
    assert "PG append_event boom" in msg


def test_dual_write_logs_when_fallback_fails_primary_ok(caplog):
    good_event = _event()
    primary = _FakeStore(name="PG")
    fallback = _FakeStore(name="SQLite", fail_methods={"append_event"})
    hybrid = HybridStorageBackend(
        primary=primary, fallback=fallback, strict_dual_write=False
    )

    with caplog.at_level(logging.WARNING, logger=HYBRID_LOGGER):
        result = hybrid.append_event(good_event)

    assert result is good_event
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "append_event" in msg
    assert "fallback" in msg
    assert "SQLite append_event boom" in msg


def test_dual_write_no_log_when_both_succeed(caplog):
    good_event = _event()
    primary = _FakeStore(name="PG")
    fallback = _FakeStore(name="SQLite")
    hybrid = HybridStorageBackend(
        primary=primary, fallback=fallback, strict_dual_write=False
    )

    with caplog.at_level(logging.WARNING, logger=HYBRID_LOGGER):
        hybrid.append_event(good_event)

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_read_with_fallback_logs_when_first_fails(caplog):
    rows = [_event("run-read")]
    primary = _FakeStore(name="PG", fail_methods={"list_events"})
    fallback = _FakeStore(name="SQLite", rows=rows)
    hybrid = HybridStorageBackend(
        primary=primary,
        fallback=fallback,
        prefer_primary_reads=True,
        strict_dual_write=False,
    )

    with caplog.at_level(logging.WARNING, logger=HYBRID_LOGGER):
        result = hybrid.list_events(limit=10, run_id="run-read")

    # Se recurre al segundo store y se devuelven sus filas.
    assert result == rows
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "list_events" in msg
    assert "primary" in msg
    assert "PG list_events boom" in msg


def test_strict_dual_write_still_raises(caplog):
    primary = _FakeStore(name="PG", fail_methods={"append_event"})
    fallback = _FakeStore(name="SQLite")
    hybrid = HybridStorageBackend(
        primary=primary, fallback=fallback, strict_dual_write=True
    )
    with pytest.raises(RuntimeError):
        hybrid.append_event(_event())
