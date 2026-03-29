"""
swarm/bootstrap_server.py — Standalone Kademlia DHT bootstrap node.

Run this on any machine with a reachable IP to create a private
entry point for your swarm.  Other nodes join with:

    python examples/run_node.py --bootstrap <this-machine-ip>

Usage:
    python swarm/bootstrap_server.py
    python examples/run_bootstrap.py   # convenience wrapper
"""

import socket
import time

from swarm.kademlia_node import KademliaNode


def run() -> None:
    node = KademliaNode()
    node.start()   # no bootstrap — this IS the first node

    # Determine best outbound-facing IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = socket.gethostbyname(socket.gethostname())

    print(f"[BOOTSTRAP] Kademlia bootstrap running on {ip}:6881", flush=True)
    print(f"[BOOTSTRAP] Other nodes join with:", flush=True)
    print(f"[BOOTSTRAP]   python examples/run_node.py --bootstrap {ip}", flush=True)
    print(f"[BOOTSTRAP] Press Ctrl+C to stop", flush=True)

    t = 0
    try:
        while True:
            time.sleep(10)
            t += 10
            peers = node.get_all_peers()
            rt_size = node.routing_table.size()
            print(
                f"[BOOTSTRAP] t+{t}s  peers={len(peers)}  routing_table={rt_size}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("[BOOTSTRAP] Shutting down.", flush=True)
        node.stop()


if __name__ == "__main__":
    run()
