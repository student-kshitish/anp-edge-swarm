"""
db/sync.py — Gossip protocol sync between nodes.
Shares unsynced sensor_readings with peers every 30 seconds
over a dedicated TCP port (50011) separate from the peer-capability
exchange (50010).  Standard library only.
"""

import json
import socket
import threading
import time

from db.query import get_unsynced
from db.store import save_sensor_reading, save_prediction, save_work_order, mark_synced
from swarm.node_identity import get_node_id

SYNC_PORT     = 50011
SYNC_INTERVAL = 30


class DBSync:

    def __init__(self, get_peers_fn):
        self.get_peers = get_peers_fn
        self.node_id   = get_node_id()
        self.running   = False

    def start(self):
        self.running = True
        threading.Thread(
            target=self._sync_server,
            daemon=True,
            name="db-sync-server",
        ).start()
        threading.Thread(
            target=self._sync_loop,
            daemon=True,
            name="db-sync-client",
        ).start()
        print(f"[DB-SYNC] Distributed sync started on port {SYNC_PORT}")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------ #
    # Client side — push unsynced records to each known peer
    # ------------------------------------------------------------------ #

    def _sync_loop(self):
        while self.running:
            time.sleep(SYNC_INTERVAL)
            peers = self.get_peers()
            own   = self._own_ip()
            for peer_id, info in peers.items():
                ip = info.get("addr") or info.get("ip")
                if ip and ip != own:
                    try:
                        self._sync_with_peer(ip)
                    except Exception:
                        pass

    def _sync_with_peer(self, ip: str):
        unsynced = get_unsynced("sensor_readings", limit=20)
        if not unsynced:
            return

        payload = json.dumps({
            "type":    "DB_SYNC",
            "from":    self.node_id,
            "table":   "sensor_readings",
            "records": unsynced,
        }).encode()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((ip, SYNC_PORT))
            sock.sendall(len(payload).to_bytes(4, "big") + payload)
        finally:
            sock.close()

        for r in unsynced:
            if r.get("record_id"):
                mark_synced("sensor_readings", r["record_id"])

        print(f"[DB-SYNC] Sent {len(unsynced)} records to {ip}")

    # ------------------------------------------------------------------ #
    # Server side — receive records pushed by peers
    # ------------------------------------------------------------------ #

    def _sync_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", SYNC_PORT))
        server.listen(5)
        server.settimeout(2)
        while self.running:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_sync,
                    args=(conn, addr),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue

    def _handle_sync(self, conn: socket.socket, addr: tuple):
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

            payload   = json.loads(data.decode())
            if payload.get("type") != "DB_SYNC":
                return

            records   = payload.get("records", [])
            table     = payload.get("table", "sensor_readings")
            from_node = payload.get("from", "unknown")
            saved     = 0

            for r in records:
                try:
                    if table == "sensor_readings":
                        save_sensor_reading(
                            r["sensor_type"],
                            json.loads(r["raw_json"]),
                            r["node_id"],
                        )
                        saved += 1
                except Exception:
                    pass

            print(f"[DB-SYNC] Received {saved} records from {addr[0]}")
        except Exception as e:
            print(f"[DB-SYNC] Handle error: {e}")
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #

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
