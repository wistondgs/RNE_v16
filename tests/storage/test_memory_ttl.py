"""B2: el TTL de memory_records se aplica en lectura y hay purga invocable.

Antes: ttl_seconds se escribia y persistia pero jamas se aplicaba en lectura
(las memorias expiradas se devolvian) y no habia forma de purgarlas.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.backends.hybrid_store import HybridStorageBackend


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _facade(db_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(db_path),
            postgres_dsn=None,
            artifact_root=db_path.parent / "artifacts",
            prefer_postgres_reads=True,
            strict_dual_write=False,
        )
    )


def _seed(storage) -> None:
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)
    # Expirada: ttl corto + created_at en el pasado (edad ~3600s > 10s).
    storage.write_memory_record(
        memory_id="mem-expired",
        run_id="run-ttl",
        episode_id="ep-1",
        scale="micro",
        structure_json={"k": "expired"},
        ttl_seconds=10,
        created_at=_iso(past),
    )
    # Vigente con ttl largo + created_at reciente.
    storage.write_memory_record(
        memory_id="mem-fresh",
        run_id="run-ttl",
        episode_id="ep-1",
        scale="micro",
        structure_json={"k": "fresh"},
        ttl_seconds=100_000,
        created_at=_iso(now),
    )
    # Sin ttl (None): nunca expira, aunque su created_at sea viejo.
    storage.write_memory_record(
        memory_id="mem-nottl",
        run_id="run-ttl",
        episode_id="ep-1",
        scale="micro",
        structure_json={"k": "nottl"},
        ttl_seconds=None,
        created_at=_iso(past),
    )


def test_read_excludes_expired_keeps_valid_and_nottl(tmp_path: Path) -> None:
    db_path = tmp_path / "mem_ttl.db"
    storage = _facade(db_path)
    try:
        _seed(storage)

        # Las tres filas estan fisicamente en la tabla.
        with sqlite3.connect(db_path) as conn:
            raw = conn.execute(
                "SELECT COUNT(*) FROM memory_records WHERE run_id = ?",
                ("run-ttl",),
            ).fetchone()[0]
        assert raw == 3

        got = {m.memory_id for m in storage.retrieve_memory_records(run_id="run-ttl")}
        # La expirada NO aparece; la vigente y la sin-ttl si.
        assert got == {"mem-fresh", "mem-nottl"}
    finally:
        storage.close()


def test_purge_deletes_only_expired(tmp_path: Path) -> None:
    db_path = tmp_path / "mem_purge.db"
    storage = _facade(db_path)
    try:
        _seed(storage)

        deleted = storage.purge_expired_memory_records()
        assert deleted == 1

        # Solo la expirada se borro fisicamente; quedan las otras dos.
        with sqlite3.connect(db_path) as conn:
            remaining = {
                row[0]
                for row in conn.execute(
                    "SELECT memory_id FROM memory_records WHERE run_id = ?",
                    ("run-ttl",),
                ).fetchall()
            }
        assert remaining == {"mem-fresh", "mem-nottl"}

        # Purga idempotente: una segunda pasada no borra nada.
        assert storage.purge_expired_memory_records() == 0
    finally:
        storage.close()


class _PurgeCountStore:
    """Stub que reporta un conteo fijo de purga y registra que se lo invocó."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.purged = False

    def purge_expired_memory_records(self) -> int:
        self.purged = True
        return self.count


def test_hybrid_purge_returns_logical_count_not_sum() -> None:
    # Bajo dual-write cada memoria lógica vive en AMBOS stores; el hybrid debe
    # devolver la cuenta LÓGICA (la del primary), no la suma (que contaría 2x cada
    # memoria), y aun así purgar físicamente ambos backends.
    primary = _PurgeCountStore(1)
    fallback = _PurgeCountStore(1)
    hybrid = HybridStorageBackend(
        primary=primary, fallback=fallback, strict_dual_write=False
    )

    deleted = hybrid.purge_expired_memory_records()

    assert deleted == 1  # cuenta lógica (primary), no 2
    assert primary.purged and fallback.purged  # ambos purgados físicamente
