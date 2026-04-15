"""
swarm/bluetooth_discovery.py — Bluetooth peer discovery via BluetoothMesh.

Exposes the same surface as swarm/discovery.py so the rest of the system
works transparently over BLE without any code changes:

    start(on_discover)   — begin scanning and announce this node
    get_known_nodes()    — return currently visible BLE peers
    broadcast_intent()   — send an INTENT message into the mesh
    stop()               — tear down BLE transport
"""

import time

from swarm.bluetooth_mesh import BluetoothMesh
from swarm.capability import get_capabilities
from swarm.node_identity import get_node_id

_mesh          = BluetoothMesh()
_bt_known_nodes: dict = {}


def start(on_discover=None) -> bool:
    """Start Bluetooth mesh discovery and announce this node.

    Returns True if BLE transport started successfully,
    False if bleak is unavailable (graceful fallback).
    """

    def handle_announce(payload: dict, from_address: str):
        node_id = payload.get("node_id")
        if node_id and node_id != get_node_id():
            _bt_known_nodes[node_id] = {
                "caps":      payload,
                "addr":      from_address,
                "transport": "bluetooth",
                "roles":     payload.get("roles", ["worker"]),
                "last_seen": time.time(),
            }
            print(f"[BT-DISC] Node discovered: {node_id[:12]} via BLE")
            if on_discover:
                on_discover(_bt_known_nodes[node_id])

    _mesh.register_handler("ANNOUNCE", handle_announce)
    success = _mesh.start()

    if success:
        cap = get_capabilities()
        _mesh.broadcast("ANNOUNCE", cap)
        print("[BT-DISC] Bluetooth discovery started")

    return success


def get_known_nodes() -> dict:
    return dict(_bt_known_nodes)


def broadcast_intent(intent: dict):
    _mesh.broadcast("INTENT", intent)


def stop():
    _mesh.stop()
