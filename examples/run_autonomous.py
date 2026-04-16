"""
examples/run_autonomous.py — Starts the system in fully autonomous mode.
No human input required after launch. Works for any scenario.
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.abspath("."))

from swarm.dht_discovery import start as start_dht, get_known_nodes
from swarm.peer_server import start_server as start_peer_server
from swarm.peer_client import exchange_with_all
from swarm.known_peers import PEER_IPS
from ml.inference_server import start_server as start_inference_server
from bus.message_bus import bus          # shared singleton used by all agents
from core.swarm_mind import SwarmMind
from agents.sensor_agent import SensorAgent

parser = argparse.ArgumentParser(description="EdgeMind Autonomous Mode")
parser.add_argument("--bootstrap", default=None, help="Bootstrap node IP")
parser.add_argument("--bluetooth", action="store_true", help="Enable BT mesh")
parser.add_argument(
    "--scenario", default="general",
    choices=["general", "surveillance", "disaster", "factory", "medical"],
    help="Deployment scenario",
)
args = parser.parse_args()

print("=" * 60)
print("  EdgeMind — Autonomous Swarm Mode")
print(f"  Scenario: {args.scenario.upper()}")
print("=" * 60)
print()

# ------------------------------------------------------------------ #
# Start transport layers
# ------------------------------------------------------------------ #
print("[BOOT] Starting transport layers...")
start_dht(bootstrap_ip=args.bootstrap)
start_peer_server()
exchange_with_all(PEER_IPS)

if args.bluetooth:
    try:
        from swarm.bluetooth_discovery import start as bt_start
        bt_start()
        print("[BOOT] Bluetooth mesh active")
    except Exception as e:
        print(f"[BOOT] BT unavailable: {e}")

start_inference_server()
print("[BOOT] All transport layers active")
print()

# ------------------------------------------------------------------ #
# Start local sensors (they publish to the shared bus under "orchestrator")
# ------------------------------------------------------------------ #
print("[BOOT] Starting local sensors...")
sensors = ["attendance", "temperature", "materials"]
for sensor_type in sensors:
    agent = SensorAgent(
        agent_id=f"auto-{sensor_type}",
        sensor_type=sensor_type,
        report_to="swarm-mind",
    )
    agent.start()
    print(f"[BOOT] Sensor started: {sensor_type}")

print()

# ------------------------------------------------------------------ #
# Start SwarmMind — the autonomous controller
# ------------------------------------------------------------------ #
mind = SwarmMind(get_peers_fn=get_known_nodes, bus=bus)
mind.start()

# Make the mind accessible to the socket server for status queries
from api import socket_server as _ss
_ss.set_swarm_mind(mind)

print()
print("[READY] System is fully autonomous")
print("[READY] Devices joining the network are detected automatically")
print("[READY] ML pipeline triggers every 30 seconds when data is ready")
print("[READY] Work orders created automatically in logs/workorders/")
print("[READY] Press Ctrl+C to stop")
print()

try:
    while True:
        time.sleep(10)
        status = mind.status()
        print(
            f"[STATUS] uptime={status['uptime_seconds']}s "
            f"devices={status['known_devices']} "
            f"cycles={status['pipeline_cycles']}"
        )
except KeyboardInterrupt:
    print()
    print("[SHUTDOWN] Stopping autonomous mode...")
    mind.stop()
