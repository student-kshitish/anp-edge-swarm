"""
agents/telemetry_agent.py — Black box recorder for the swarm.

Subscribes to all events via wildcard and persists them to a
SQLite time-series table for post-mortem analysis and monitoring.

Writes are coalesced through a background queue so the hot event
path never blocks on I/O.
"""

import time
import json
import queue
import threading
from agents.base_agent import BaseAgent
from bus.event_bus import get_event_bus
from db.db_agent_singleton import get_db


class TelemetryAgent(BaseAgent):

    def __init__(self, agent_id="telemetry-agent"):
        super().__init__(agent_id=agent_id, role="telemetry")
        self.event_count  = 0
        self.event_types  = {}
        self.running      = False
        self._write_queue = queue.Queue()
        self._ensure_table()
        # Single background writer — one connection, no per-event connect()
        self._writer = threading.Thread(
            target=self._writer_loop, daemon=True, name="telemetry-writer"
        )
        self._writer.start()

    def _ensure_table(self):
        try:
            db = get_db()
            if db.get_db_type() == "sqlite":
                import sqlite3
                conn = sqlite3.connect(db.adapter.db_path)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp   REAL    NOT NULL,
                        event_type  TEXT    NOT NULL,
                        sender_id   TEXT,
                        priority    TEXT,
                        data_json   TEXT,
                        indexed_at  TEXT    DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_telemetry_ts
                        ON telemetry_events(timestamp DESC)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_telemetry_type
                        ON telemetry_events(event_type)
                """)
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[TELEMETRY] Table init warning: {e}")

    def _writer_loop(self):
        """Drains the write queue using a single persistent connection."""
        db = get_db()
        if db.get_db_type() != "sqlite":
            return

        import sqlite3
        conn = None
        while True:
            try:
                record = self._write_queue.get()
                if record is None:    # shutdown sentinel
                    break
                if conn is None:
                    conn = sqlite3.connect(db.adapter.db_path)
                conn.execute("""
                    INSERT INTO telemetry_events
                        (timestamp, event_type, sender_id, priority, data_json)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    record["timestamp"],
                    record["event_type"],
                    record["sender_id"],
                    record["priority"],
                    record["data_json"],
                ))
                conn.commit()
            except Exception:
                # Reconnect on next write attempt
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None

    def start(self):
        self.running = True
        eb = get_event_bus()
        eb.subscribe("*", self._on_any_event, agent_id="telemetry-wildcard")
        print("[TELEMETRY] Black box recorder started — capturing all swarm events")
        super().start()

    def stop(self):
        self.running = False
        self._write_queue.put(None)  # signal writer to exit
        super().stop()

    def _on_any_event(self, event: dict):
        self.event_count += 1
        etype = event.get("event_type", "unknown")
        self.event_types[etype] = self.event_types.get(etype, 0) + 1

        self._write_queue.put({
            "timestamp":  event.get("timestamp", time.time()),
            "event_type": etype,
            "sender_id":  event.get("sender_id", ""),
            "priority":   event.get("priority", "MEDIUM"),
            "data_json":  json.dumps(event.get("data", {})),
        })

    def get_status(self) -> dict:
        return {
            "total_events": self.event_count,
            "event_types":  dict(self.event_types),
            "top_5_types":  dict(sorted(
                self.event_types.items(),
                key=lambda x: x[1], reverse=True,
            )[:5]),
            "queue_depth":  self._write_queue.qsize(),
        }

    def query_by_type(self, event_type: str, limit: int = 100) -> list:
        try:
            db = get_db()
            if db.get_db_type() == "sqlite":
                import sqlite3
                conn = sqlite3.connect(db.adapter.db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT * FROM telemetry_events
                    WHERE event_type = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (event_type, limit)).fetchall()
                conn.close()
                return [dict(r) for r in rows]
        except Exception:
            pass
        return []

    def query_recent(self, limit: int = 50) -> list:
        try:
            db = get_db()
            if db.get_db_type() == "sqlite":
                import sqlite3
                conn = sqlite3.connect(db.adapter.db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT * FROM telemetry_events
                    ORDER BY timestamp DESC LIMIT ?
                """, (limit,)).fetchall()
                conn.close()
                return [dict(r) for r in rows]
        except Exception:
            pass
        return []
