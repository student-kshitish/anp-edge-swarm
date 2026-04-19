"""
examples/run_topology.py — Visualize the live swarm topology.

Starts peer discovery, waits for nodes to appear, then generates
an ASCII diagram and saves DOT + JSON snapshots.
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath("."))

from swarm.dht_discovery import start as start_dht
from swarm.peer_server import start_server as start_peer_server
from swarm.peer_client import exchange_with_all
from swarm.known_peers import PEER_IPS
from swarm.visualize import save_snapshot, generate_ascii_diagram, get_my_neighbors

print("Starting discovery...")
start_dht()
start_peer_server()
exchange_with_all(PEER_IPS)

print("Waiting 10s for peer discovery...")
time.sleep(10)

topology = get_my_neighbors()
print(generate_ascii_diagram(topology))

snapshot = save_snapshot()
print(f"\nSnapshot saved: {snapshot['dot']}")
print(f"Render with: dot -Tpng {snapshot['dot']} -o topology.png")
