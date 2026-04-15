"""
swarm/bluetooth_mesh.py — Multi-hop mesh routing over BLE.

Messages relay device-to-device up to MAX_HOPS times.
A seen-message cache (keyed by msg_id, TTL=60 s) prevents
infinite forwarding loops in the mesh.
"""

import json
import threading
import time
import uuid

from swarm.bluetooth_transport import BluetoothTransport

MAX_HOPS       = 5
SEEN_CACHE_TTL = 60   # seconds


class BluetoothMesh:

    def __init__(self):
        self.transport  = BluetoothTransport()
        self.node_id    = self.transport.node_id
        self._seen      = {}          # msg_id -> timestamp
        self._handlers  = {}          # msg_type -> callable
        self._lock      = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the underlying BLE transport.

        Returns True on success, False if bleak is unavailable.
        """
        return self.transport.start(on_message=self._on_receive)

    def register_handler(self, msg_type: str, handler):
        """Register a callback for a specific message type.

        handler(payload: dict, from_address: str) -> None
        """
        self._handlers[msg_type] = handler

    def broadcast(self, msg_type: str, payload: dict,
                  destination: str = "ALL"):
        """Build a mesh envelope and send to all known BLE peers."""
        msg = {
            "msg_id":      str(uuid.uuid4()),
            "type":        msg_type,
            "origin":      self.node_id,
            "destination": destination,
            "hop_count":   0,
            "max_hops":    MAX_HOPS,
            "payload":     payload,
            "seen_by":     [self.node_id],
            "timestamp":   time.time(),
        }
        self._mark_seen(msg["msg_id"])
        self.transport.send_message(msg)
        print(f"[MESH] Broadcast {msg_type} hops=0/{MAX_HOPS}")

    def get_peers(self) -> dict:
        return self.transport.get_known_peers()

    def stop(self):
        self.transport.stop()

    # ------------------------------------------------------------------
    # Internal receive / relay logic
    # ------------------------------------------------------------------

    def _on_receive(self, raw_data: bytes, from_address: str):
        try:
            msg = json.loads(raw_data.decode())
        except Exception:
            return

        msg_id = msg.get("msg_id")
        if not msg_id:
            return

        # Drop duplicates
        if self._is_seen(msg_id):
            return
        self._mark_seen(msg_id)

        destination = msg.get("destination", "ALL")
        msg_type    = msg.get("type")

        # Deliver to a local handler if addressed here or broadcast
        if destination in ("ALL", self.node_id):
            handler = self._handlers.get(msg_type)
            if handler:
                handler(msg["payload"], from_address)

        # Relay if hops remain and message is not point-to-point to us
        if (msg.get("hop_count", 0) < msg.get("max_hops", MAX_HOPS)
                and destination != self.node_id):
            msg["hop_count"] += 1
            if self.node_id not in msg["seen_by"]:
                msg["seen_by"].append(self.node_id)
            self.transport.send_message(msg)
            print(f"[MESH] Relayed {msg_type} hop={msg['hop_count']}")

    # ------------------------------------------------------------------
    # Seen-message cache helpers
    # ------------------------------------------------------------------

    def _is_seen(self, msg_id: str) -> bool:
        with self._lock:
            self._clean_seen()
            return msg_id in self._seen

    def _mark_seen(self, msg_id: str):
        with self._lock:
            self._seen[msg_id] = time.time()

    def _clean_seen(self):
        """Evict entries older than SEEN_CACHE_TTL (called under lock)."""
        now = time.time()
        self._seen = {
            k: v for k, v in self._seen.items()
            if now - v < SEEN_CACHE_TTL
        }
