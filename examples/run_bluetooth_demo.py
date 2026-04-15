"""
examples/run_bluetooth_demo.py — Standalone BLE mesh demo.

Scans for nearby EDGEMIND nodes, announces this node, and relays messages
through the mesh.  Useful for verifying BLE transport on a single machine
or between two devices before integrating with the full swarm.

Requirements:
    pip install bleak

Usage:
    python examples/run_bluetooth_demo.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))

from swarm.bluetooth_mesh import BluetoothMesh
from swarm.capability import get_capabilities


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

    cap = get_capabilities()
    print(f"My node: {cap['node_id'][:12]}")
    print("Scanning for EDGEMIND nodes every 10 seconds...")
    print("Press Ctrl+C to stop")
    print()

    try:
        count = 0
        while True:
            mesh.broadcast("ANNOUNCE", cap)
            peers = mesh.get_peers()
            count += 1
            print(f"[t+{count * 10}s] BLE peers found: {len(peers)}")
            for addr, info in peers.items():
                print(f"  {info.get('name', '?')} @ {addr}")
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping...")
        mesh.stop()


if __name__ == "__main__":
    main()
