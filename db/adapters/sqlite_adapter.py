"""
db/adapters/sqlite_adapter.py — SQLite adapter.
Works on Victus, Windows, Android Termux — Python built-in, zero deps.

Uses the same edgemind.db file as db/schema.py.  The CREATE TABLE IF NOT
EXISTS statements are intentionally minimal so they don't clobber the
richer schema already created by schema.py's init_db().  Inserts use only
columns that exist in both schemas; schema.py columns not touched here
(unit, anomaly_count, etc.) simply retain their DEFAULT values.
"""

import sqlite3
import json
import uuid
import threading
import os
from datetime import datetime, timezone

from db.adapters.base import BaseDBAdapter


class SQLiteAdapter(BaseDBAdapter):

    def __init__(self, db_path: str = "edgemind.db"):
        self.db_path = db_path
        self._lock   = threading.Lock()

    def get_type(self) -> str:
        return "sqlite"

    def init(self) -> None:
        with self._lock:
            conn = self._conn()
            # Minimal CREATE TABLE IF NOT EXISTS — only fires on a
            # fresh database where schema.py has not yet run.
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sensor_readings (
                    record_id   TEXT PRIMARY KEY,
                    timestamp   TEXT,
                    node_id     TEXT,
                    sensor_type TEXT,
                    value_num   REAL,
                    value_text  TEXT,
                    raw_json    TEXT,
                    synced      INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS work_orders (
                    record_id   TEXT PRIMARY KEY,
                    timestamp   TEXT,
                    node_id     TEXT,
                    priority    TEXT,
                    status      TEXT DEFAULT 'OPEN',
                    description TEXT,
                    raw_json    TEXT,
                    synced      INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    record_id   TEXT PRIMARY KEY,
                    timestamp   TEXT,
                    node_id     TEXT,
                    status      TEXT,
                    urgency     TEXT,
                    action      TEXT,
                    raw_json    TEXT,
                    synced      INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS peers (
                    node_id     TEXT PRIMARY KEY,
                    ip          TEXT,
                    transport   TEXT,
                    last_seen   TEXT,
                    caps_json   TEXT
                );
            """)
            conn.commit()
            conn.close()
        print(f"[DB] SQLite initialized: {self.db_path}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def save(self, table: str, record: dict) -> str:
        record_id = record.get("record_id", str(uuid.uuid4()))
        record    = dict(record)          # don't mutate caller's dict
        record["record_id"] = record_id
        record.setdefault(
            "timestamp",
            datetime.now(timezone.utc).isoformat(),
        )

        cols         = list(record.keys())
        vals         = list(record.values())
        placeholders = ",".join("?" for _ in cols)
        col_str      = ",".join(cols)

        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({col_str}) "
                    f"VALUES ({placeholders})",
                    vals,
                )
                conn.commit()
            except Exception:
                # Graceful fallback: store only the universal columns that
                # every table is guaranteed to have (record_id + raw_json).
                try:
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} "
                        f"(record_id, timestamp, node_id, raw_json) "
                        f"VALUES (?,?,?,?)",
                        (
                            record_id,
                            record.get("timestamp", ""),
                            record.get("node_id", "local"),
                            json.dumps(record),
                        ),
                    )
                    conn.commit()
                except Exception:
                    pass   # table schema mismatch — silently skip
            conn.close()
        return record_id

    def fetch(self, table: str, filters: dict = None,
              limit: int = 100) -> list:
        with self._lock:
            conn = self._conn()
            try:
                if filters:
                    where = " AND ".join(f"{k}=?" for k in filters)
                    rows  = conn.execute(
                        f"SELECT * FROM {table} WHERE {where} "
                        f"ORDER BY timestamp DESC LIMIT ?",
                        list(filters.values()) + [limit],
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT * FROM {table} "
                        f"ORDER BY timestamp DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                result = [dict(r) for r in rows]
            except Exception:
                result = []
            conn.close()
        return result

    def update(self, table: str, record_id: str,
               data: dict) -> bool:
        with self._lock:
            conn = self._conn()
            try:
                sets = ",".join(f"{k}=?" for k in data)
                conn.execute(
                    f"UPDATE {table} SET {sets} WHERE record_id=?",
                    list(data.values()) + [record_id],
                )
                conn.commit()
            except Exception:
                pass
            conn.close()
        return True

    def delete(self, table: str, record_id: str) -> bool:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE record_id=?",
                    (record_id,),
                )
                conn.commit()
            except Exception:
                pass
            conn.close()
        return True

    def count(self, table: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except Exception:
                n = 0
            conn.close()
        return n
