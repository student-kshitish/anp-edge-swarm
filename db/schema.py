"""
db/schema.py — SQLite schema and thread-safe connection manager.
Works on all platforms. WAL mode for concurrent reads.
"""

import sqlite3
import os
import threading
import json
from datetime import datetime, timezone

DB_PATH = os.environ.get("EDGEMIND_DB", "edgemind.db")
_lock   = threading.Lock()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with _lock:
        conn = get_connection()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id   TEXT    UNIQUE,
            timestamp   TEXT    NOT NULL,
            node_id     TEXT    NOT NULL,
            sensor_type TEXT    NOT NULL,
            value_num   REAL,
            value_text  TEXT,
            unit        TEXT,
            status      TEXT,
            raw_json    TEXT    NOT NULL,
            synced      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS work_orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            wo_id       TEXT    UNIQUE NOT NULL,
            created_at  TEXT    NOT NULL,
            priority    TEXT    NOT NULL,
            status      TEXT    DEFAULT 'OPEN',
            description TEXT,
            site_status TEXT,
            anomalies   TEXT,
            sensor_data TEXT,
            node_id     TEXT,
            closed_at   TEXT,
            synced      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS peers (
            node_id     TEXT    PRIMARY KEY,
            ip          TEXT,
            transport   TEXT,
            os          TEXT,
            ram_gb      REAL,
            cpu_cores   INTEGER,
            roles       TEXT,
            models      TEXT,
            first_seen  TEXT,
            last_seen   TEXT,
            caps_json   TEXT
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id     TEXT    UNIQUE,
            timestamp     TEXT    NOT NULL,
            node_id       TEXT,
            status        TEXT,
            urgency       TEXT,
            anomaly_count INTEGER DEFAULT 0,
            anomalies     TEXT,
            trends        TEXT,
            action        TEXT,
            nodes_used    INTEGER DEFAULT 0,
            elapsed_ms    INTEGER,
            raw_json      TEXT,
            synced        INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        TEXT,
            peer_id          TEXT,
            records_sent     INTEGER DEFAULT 0,
            records_received INTEGER DEFAULT 0,
            direction        TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_sensor_ts
            ON sensor_readings(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sensor_type
            ON sensor_readings(sensor_type);
        CREATE INDEX IF NOT EXISTS idx_sensor_synced
            ON sensor_readings(synced);
        CREATE INDEX IF NOT EXISTS idx_pred_ts
            ON predictions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_wo_status
            ON work_orders(status);
        """)
        conn.commit()
        conn.close()
        print(f"[DB] Initialized: {DB_PATH}")
