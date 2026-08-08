# event_log_sqlite.py – Persistencia de eventos en SQLite para AEON FENIX-Δ
default_db_path = "aeon_event_log.db"

import json
import os
import sqlite3
import threading
from datetime import datetime


def configure_sqlite_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Aplica los PRAGMA de conexión estándar del proyecto (fuente única, B38-C12).

    Debe invocarse tras CADA ``sqlite3.connect(...)`` del runtime:

    - ``journal_mode=WAL``: lectores no bloquean escritores (y viceversa);
      mitiga "database is locked" bajo la amplificación de escritura por
      episodio (SMG + EventBus + court_runtime + artifacts).
    - ``busy_timeout=5000``: ante un lock, espera hasta 5 s en vez de fallar
      inmediatamente.
    - ``synchronous=NORMAL``: durabilidad adecuada en WAL sin fsync por commit.
    - ``foreign_keys=ON``: integridad referencial (SQLite la trae OFF por
      defecto y es per-conexión).

    Devuelve la misma conexión para permitir uso en línea:
    ``with configure_sqlite_connection(sqlite3.connect(path)) as conn:``.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class EventLogSQLite:
    """
    Ledger SQLite con compatibilidad histórica:
    - esquema canónico: `event_type`
    - esquema legacy: `eve_type`
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get("AEON_EVENT_DB", default_db_path)
        self._lock = threading.Lock()
        self._event_column = "event_type"
        self._ensure_schema()

    def _list_columns(self, conn, table_name):
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def _ensure_schema(self):
        with configure_sqlite_connection(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    event_type TEXT NOT NULL,
                    payload TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )
            cols = self._list_columns(conn, "events")
            has_event_type = "event_type" in cols
            has_eve_type = "eve_type" in cols

            # Migracion one-way: eve_type -> event_type
            if has_eve_type and not has_event_type:
                conn.execute("ALTER TABLE events RENAME TO events_legacy_eve_type")
                conn.execute(
                    """
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT,
                        event_type TEXT NOT NULL,
                        payload TEXT,
                        timestamp TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO events (id, event_type, payload, timestamp)
                    SELECT id, eve_type, payload, timestamp
                    FROM events_legacy_eve_type
                    """
                )
                has_event_type = True
                has_eve_type = False

            cols = self._list_columns(conn, "events")
            if "event_id" not in cols:
                conn.execute("ALTER TABLE events ADD COLUMN event_id TEXT")
            # Older SQLite rows stored the deterministic EA1 event identity inside
            # the JSON payload. Backfill one canonical occurrence per identity;
            # legacy duplicates remain readable but cannot claim the unique key.
            conn.execute(
                """
                UPDATE events
                SET event_id = json_extract(payload, '$.event_id')
                WHERE id IN (
                    SELECT MIN(id)
                    FROM events
                    WHERE json_extract(payload, '$.event_id') IS NOT NULL
                    GROUP BY json_extract(payload, '$.event_id')
                )
                AND event_id IS NULL
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_event_id "
                "ON events(event_id) WHERE event_id IS NOT NULL"
            )
            self._event_column = "event_type" if has_event_type else "eve_type"
            conn.commit()

    def log_event(self, event_type, payload, timestamp=None, event_id=None):
        ts = timestamp or datetime.utcnow().isoformat()
        with self._lock, configure_sqlite_connection(
            sqlite3.connect(self.db_path)
        ) as conn:
            cursor = conn.execute(
                f"INSERT INTO events (event_id, {self._event_column}, payload, timestamp) "
                "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (event_id, event_type, json.dumps(payload), ts),
            )
            conn.commit()
            return cursor.rowcount == 1

    def get_events(self, limit=200, event_types=None, run_id=None):
        query = f"SELECT event_id, {self._event_column}, payload, timestamp FROM events"
        clauses = []
        params = []
        if event_types:
            placeholders = ",".join(["?"] * len(event_types))
            clauses.append(f"{self._event_column} IN ({placeholders})")
            params.extend(event_types)
        if run_id is not None:
            # run_id se persiste dentro del payload JSON (ver
            # SQLiteStorageBackend.append_event). Se filtra en SQL **antes** del LIMIT
            # para no perder eventos del run cuando hay > limit eventos globales
            # (paridad con Postgres, que filtra run_id en SQL).
            clauses.append(
                "COALESCE(json_extract(payload, '$.run_id'), "
                "json_extract(payload, '$._run_id')) = ?"
            )
            params.append(run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with configure_sqlite_connection(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "event_id": row[0],
                "event": row[1],
                "payload": json.loads(row[2]) if row[2] else None,
                "timestamp": row[3],
            }
            for row in rows
        ][::-1]
