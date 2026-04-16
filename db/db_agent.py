"""
db/db_agent.py — Database Abstraction Agent.

Auto-detects the best available database on the current node and uses it.
Priority: PostgreSQL → SQLite → TinyDB → JSON files.

Translates (normalises) records between different DB formats automatically
so every node can share data regardless of what database it uses.

Sync uses TCP port 50011 — same port as db/sync.py.
Do NOT start both DBSync and DBAgent.start_sync() on the same node;
only one should be active to avoid EADDRINUSE.
"""

import json
import uuid
import time
import socket
import threading
from datetime import datetime, timezone

from swarm.node_identity import get_node_id


class DBAgent:

    def __init__(self, get_peers_fn=None):
        self.node_id   = get_node_id()
        self.get_peers = get_peers_fn
        self.adapter   = None
        self.running   = False
        self._detect_and_init()

    # ------------------------------------------------------------------ #
    # Adapter detection
    # ------------------------------------------------------------------ #

    def _detect_and_init(self):
        # 1. Try PostgreSQL
        try:
            import psycopg2                                      # noqa: F401
            from db.adapters.postgres_adapter import PostgresAdapter
            self.adapter = PostgresAdapter()
            self.adapter.init()
            print("[DB-AGENT] Using PostgreSQL")
            return
        except Exception:
            pass

        # 2. Try SQLite (Python built-in — almost always succeeds)
        try:
            from db.adapters.sqlite_adapter import SQLiteAdapter
            self.adapter = SQLiteAdapter()
            self.adapter.init()
            print("[DB-AGENT] Using SQLite")
            return
        except Exception:
            pass

        # 3. Try TinyDB
        try:
            import tinydb                                        # noqa: F401
            from db.adapters.tinydb_adapter import TinyDBAdapter
            self.adapter = TinyDBAdapter()
            self.adapter.init()
            print("[DB-AGENT] Using TinyDB")
            return
        except Exception:
            pass

        # 4. JSON fallback — always works
        from db.adapters.json_adapter import JSONAdapter
        self.adapter = JSONAdapter()
        self.adapter.init()
        print("[DB-AGENT] Using JSON files (fallback)")

    # ------------------------------------------------------------------ #
    # Generic CRUD (delegates to adapter)
    # ------------------------------------------------------------------ #

    def save(self, table: str, record: dict) -> str:
        record = dict(record)
        record.setdefault("node_id", self.node_id)
        return self.adapter.save(table, record)

    def fetch(self, table: str, filters: dict = None,
              limit: int = 100) -> list:
        return self.adapter.fetch(table, filters, limit)

    def update(self, table: str, record_id: str,
               data: dict) -> bool:
        return self.adapter.update(table, record_id, data)

    def delete(self, table: str, record_id: str) -> bool:
        return self.adapter.delete(table, record_id)

    def count(self, table: str) -> int:
        return self.adapter.count(table)

    def get_db_type(self) -> str:
        return self.adapter.get_type() if self.adapter else "none"

    # ------------------------------------------------------------------ #
    # Domain-specific helpers
    # ------------------------------------------------------------------ #

    def save_sensor_reading(self, sensor_type: str,
                            raw_data: dict) -> str:
        record = {
            "sensor_type": sensor_type,
            "value_num":   (raw_data.get("celsius")
                            or raw_data.get("count")
                            or raw_data.get("qty")),
            "value_text":  (raw_data.get("item")
                            or raw_data.get("status")),
            "raw_json":    json.dumps(raw_data),
            "synced":      0,
        }
        return self.save("sensor_readings", record)

    def save_work_order(self, wo: dict) -> str:
        record = {
            "record_id":   wo.get("work_order_id", str(uuid.uuid4())),
            "priority":    wo.get("priority", "LOW"),
            "status":      "OPEN",
            "description": wo.get("description", ""),
            "raw_json":    json.dumps(wo),
            "synced":      0,
        }
        return self.save("work_orders", record)

    def save_prediction(self, result: dict,
                        elapsed_ms: int = 0) -> str:
        record = {
            "status":   result.get("status", "OK"),
            "urgency":  result.get("action_urgency", "LOW"),
            "action":   result.get("recommended_action", ""),
            "raw_json": json.dumps(result),
            "synced":   0,
        }
        return self.save("predictions", record)

    def get_history(self, limit: int = 50) -> list:
        return self.fetch("predictions", limit=limit)

    def get_recent_readings(self, sensor_type: str = None,
                            limit: int = 100) -> list:
        filters = {"sensor_type": sensor_type} if sensor_type else None
        return self.fetch("sensor_readings", filters, limit)

    # ------------------------------------------------------------------ #
    # Distributed sync (gossip over TCP 50011)
    # NOTE: Do not run alongside db/sync.py DBSync — both bind port 50011
    # ------------------------------------------------------------------ #

    def start_sync(self, sync_interval: int = 30):
        if not self.get_peers:
            return
        self.running = True
        threading.Thread(
            target=self._sync_server,
            daemon=True,
            name="db-agent-server",
        ).start()
        threading.Thread(
            target=self._sync_loop,
            args=(sync_interval,),
            daemon=True,
            name="db-agent-sync",
        ).start()
        print("[DB-AGENT] Distributed sync started")

    def stop(self):
        self.running = False

    def _sync_loop(self, interval: int):
        while self.running:
            time.sleep(interval)
            peers = self.get_peers()
            own   = self._own_ip()
            for peer_id, info in peers.items():
                ip = info.get("addr") or info.get("ip", "")
                if ip and ip != own:
                    try:
                        self._push_to_peer(ip)
                    except Exception:
                        pass

    def _push_to_peer(self, ip: str):
        unsynced = self.fetch(
            "sensor_readings",
            filters={"synced": 0},
            limit=20,
        )
        if not unsynced:
            return

        payload = json.dumps({
            "type":    "DB_SYNC",
            "from":    self.node_id,
            "db_type": self.get_db_type(),
            "table":   "sensor_readings",
            "records": unsynced,
        }).encode()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((ip, 50011))
            sock.sendall(len(payload).to_bytes(4, "big") + payload)
        finally:
            sock.close()

        for r in unsynced:
            rid = r.get("record_id")
            if rid:
                self.update("sensor_readings", rid, {"synced": 1})

        print(f"[DB-AGENT] Synced {len(unsynced)} records to {ip}")

    def _sync_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", 50011))
        server.listen(5)
        while self.running:
            try:
                server.settimeout(2)
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_incoming,
                    args=(conn, addr),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue

    def _handle_incoming(self, conn: socket.socket, addr: tuple):
        try:
            raw_len = conn.recv(4)
            if not raw_len:
                return
            msg_len = int.from_bytes(raw_len, "big")
            data    = b""
            while len(data) < msg_len:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk

            payload = json.loads(data.decode())
            if payload.get("type") != "DB_SYNC":
                return

            records   = payload.get("records", [])
            from_node = payload.get("from", "?")
            from_db   = payload.get("db_type", "?")
            saved     = 0
            for r in records:
                try:
                    normalized = self._normalize_record(r)
                    self.save("sensor_readings", normalized)
                    saved += 1
                except Exception:
                    pass
            print(
                f"[DB-AGENT] Received {saved} records "
                f"from {from_node[:12]} ({from_db})"
            )
        except Exception as e:
            print(f"[DB-AGENT] Incoming error: {e}")
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Normalisation — universal record shape regardless of source DB
    # ------------------------------------------------------------------ #

    def _normalize_record(self, record: dict) -> dict:
        return {
            "record_id":   record.get("record_id", str(uuid.uuid4())),
            "timestamp":   record.get(
                               "timestamp",
                               datetime.now(timezone.utc).isoformat(),
                           ),
            "node_id":     record.get("node_id", "unknown"),
            "sensor_type": record.get("sensor_type", "unknown"),
            "value_num":   record.get("value_num"),
            "value_text":  record.get("value_text"),
            "raw_json":    record.get("raw_json", "{}"),
            "synced":      1,   # already synced — we received it
        }

    # ------------------------------------------------------------------ #
    # Observability
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        return {
            "db_type":         self.get_db_type(),
            "node_id":         self.node_id[:12],
            "sensor_readings": self.count("sensor_readings"),
            "work_orders":     self.count("work_orders"),
            "predictions":     self.count("predictions"),
            "sync_running":    self.running,
        }

    @staticmethod
    def _own_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
