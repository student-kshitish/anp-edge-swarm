"""
examples/run_bluetooth_demo.py — Standalone BLE mesh demo.

Scans for nearby EDGEMIND nodes, announces this node, and relays messages
through the mesh.  Also probes a set of statically known Bluetooth MACs via
RFCOMM so two machines can find each other without waiting for BLE scan to
surface them.

Requirements:
    pip install bleak

Usage:
    python examples/run_bluetooth_demo.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath("."))

from swarm.bluetooth_mesh import BluetoothMesh
from swarm.capability import get_capabilities

# Known Bluetooth MAC addresses of other EdgeMind nodes.
# Add your devices here — format: "MAC": "human-readable-name"
KNOWN_BT_PEERS = {
    "C4:75:AB:00:54:2D": "windows-laptop",
    "50:2E:91:20:D0:33": "victus-linux",
}


def main():
    print("=" * 50)
    print("  EdgeMind Bluetooth Mesh Demo")
    print("=" * 50)
    print("Requires: pip install bleak")
    print()

    mesh = BluetoothMesh()

    def on_announce(payload: dict, addr: str):
        node_id = payload.get("node_id", "?")
        print(f"[DEMO] Discovered node: {node_id[:12]} via {addr}")

    mesh.register_handler("ANNOUNCE", on_announce)

    if not mesh.start():
        print("Bluetooth not available on this device")
        return

    # After start(), probe each statically known peer via RFCOMM.
    # A 6-second delay lets the RFCOMM server bind and start listening
    # before we attempt outbound connections.
    def connect_static_peers():
        time.sleep(6)
        for mac, name in KNOWN_BT_PEERS.items():
            print(f"[DEMO] Trying static peer {name} @ {mac}")
            threading.Thread(
                target=mesh.transport._try_rfcomm_connect,
                args=(mac,),
                daemon=True,
            ).start()

    threading.Thread(target=connect_static_peers, daemon=True).start()

    cap = get_capabilities()
    print(f"My node: {cap['node_id'][:12]}")
    print("Scanning for EDGEMIND nodes every 10 seconds...")
    print("Press Ctrl+C to stop")
    print()

    try:
        count = 0
        while True:
            mesh.broadcast("ANNOUNCE", cap)
            count += 1

            ble_peers    = mesh.get_peers()
            rfcomm_peers = mesh.transport.get_known_peers()
            total        = len(ble_peers) + len(rfcomm_peers)

            print(f"[t+{count * 10}s] BLE peers={len(ble_peers)} "
                  f"RFCOMM peers={len(rfcomm_peers)} total={total}")

            for addr, info in ble_peers.items():
                print(f"  BLE:    {info.get('name', '?')} @ {addr}")

            for addr, info in rfcomm_peers.items():
                node_id = info.get("node_id", "?")
                print(f"  RFCOMM: {node_id[:12]} @ {addr}")

            time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping...")
        mesh.stop()


if __name__ == "__main__":
    main()
