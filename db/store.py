"""
db/store.py — Write operations.
Every record gets a UUID record_id for distributed deduplication:
  same record arriving from two nodes is silently ignored (INSERT OR IGNORE).
"""

import json
import uuid
from db.schema import get_connection, _lock, now

_ALLOWED_TABLES = frozenset({
    "sensor_readings", "work_orders", "predictions",
    "peers", "sync_log", "telemetry_events",
})


def _record_id() -> str:
    return str(uuid.uuid4())


def _check_table(table: str) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Unknown table: {table!r}")


def save_sensor_reading(sensor_type: str, raw_data: dict,
                        node_id: str = "local") -> str:
    record_id  = _record_id()
    value_num  = None
    value_text = None

    if sensor_type == "temperature":
        value_num  = raw_data.get("celsius")
    elif sensor_type == "attendance":
        value_num  = raw_data.get("count")
        value_text = raw_data.get("status")
    elif sensor_type == "materials":
        value_num  = raw_data.get("qty")
        value_text = raw_data.get("item")

    with _lock:
        conn = get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO sensor_readings
                (record_id, timestamp, node_id, sensor_type,
                 value_num, value_text, unit, status, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                record_id, now(), node_id, sensor_type,
                value_num, value_text,
                raw_data.get("unit", ""),
                raw_data.get("status", ""),
                json.dumps(raw_data),
            ),
        )
        conn.commit()
        conn.close()
    return record_id


def save_work_order(wo: dict, node_id: str = "local") -> str:
    wo_id = wo.get("work_order_id", f"WO-{_record_id()[:8]}")
    with _lock:
        conn = get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO work_orders
                (wo_id, created_at, priority, status,
                 description, site_status, anomalies,
                 sensor_data, node_id)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                wo_id,
                wo.get("created_at", now()),
                wo.get("priority", "LOW"),
                wo.get("status", "OPEN"),
                wo.get("description", ""),
                wo.get("site_status", ""),
                json.dumps(wo.get("anomalies", [])),
                json.dumps(wo.get("sensor_snapshot", {})),
                node_id,
            ),
        )
        conn.commit()
        conn.close()
    return wo_id


def save_peer(node_id: str, caps: dict, ip: str,
              transport: str = "tcp") -> None:
    inner = caps.get("caps", caps)
    with _lock:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO peers
                (node_id, ip, transport, os, ram_gb,
                 cpu_cores, roles, models,
                 first_seen, last_seen, caps_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(node_id) DO UPDATE SET
                ip        = excluded.ip,
                last_seen = excluded.last_seen,
                caps_json = excluded.caps_json
            """,
            (
                node_id, ip, transport,
                inner.get("os", ""),
                inner.get("ram_gb", 0),
                inner.get("cpu_cores", 0),
                json.dumps(inner.get("roles", [])),
                json.dumps(inner.get("models", [])),
                now(), now(),
                json.dumps(caps),
            ),
        )
        conn.commit()
        conn.close()


def save_prediction(result: dict, node_id: str = "local",
                    elapsed_ms: int = 0) -> str:
    record_id = _record_id()
    with _lock:
        conn = get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO predictions
                (record_id, timestamp, node_id, status,
                 urgency, anomaly_count, anomalies, trends,
                 action, nodes_used, elapsed_ms, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record_id, now(), node_id,
                result.get("status", "OK"),
                result.get("action_urgency", "LOW"),
                len(result.get("anomalies_found", [])),
                json.dumps(result.get("anomalies_found", [])),
                json.dumps(result.get("trends", {})),
                result.get("recommended_action", ""),
                result.get("nodes_contributed", 0),
                elapsed_ms,
                json.dumps(result),
            ),
        )
        conn.commit()
        conn.close()
    return record_id


def mark_synced(table: str, record_id: str) -> None:
    _check_table(table)
    with _lock:
        conn = get_connection()
        conn.execute(
            f"UPDATE {table} SET synced=1 WHERE record_id=?",
            (record_id,),
        )
        conn.commit()
        conn.close()
