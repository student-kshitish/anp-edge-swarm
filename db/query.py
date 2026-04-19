"""
db/query.py — Read operations for the local SQLite database.
All functions return plain dicts (sqlite3.Row already converted).
"""

import json
from db.schema import get_connection

_ALLOWED_TABLES = frozenset({
    "sensor_readings", "work_orders", "predictions",
    "peers", "sync_log", "telemetry_events",
})


def _check_table(table: str) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Unknown table: {table!r}")


def get_recent_readings(sensor_type: str = None,
                        limit: int = 100,
                        node_id: str = None) -> list:
    conn = get_connection()
    if sensor_type and node_id:
        rows = conn.execute(
            """
            SELECT * FROM sensor_readings
            WHERE sensor_type=? AND node_id=?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (sensor_type, node_id, limit),
        ).fetchall()
    elif sensor_type:
        rows = conn.execute(
            """
            SELECT * FROM sensor_readings
            WHERE sensor_type=?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (sensor_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM sensor_readings
            ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unsynced(table: str, limit: int = 50) -> list:
    _check_table(table)
    conn = get_connection()
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE synced=0 LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_work_orders(status: str = None, limit: int = 20) -> list:
    conn = get_connection()
    if status:
        rows = conn.execute(
            """
            SELECT * FROM work_orders
            WHERE status=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM work_orders
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_predictions(limit: int = 20) -> list:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM predictions
        ORDER BY timestamp DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_peer_list() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM peers ORDER BY last_seen DESC",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_connection()
    stats = {
        "total_readings":    conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0],
        "total_work_orders": conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0],
        "open_work_orders":  conn.execute("SELECT COUNT(*) FROM work_orders WHERE status='OPEN'").fetchone()[0],
        "total_predictions": conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0],
        "total_peers":       conn.execute("SELECT COUNT(*) FROM peers").fetchone()[0],
        "unsynced_readings": conn.execute("SELECT COUNT(*) FROM sensor_readings WHERE synced=0").fetchone()[0],
    }
    conn.close()
    return stats
