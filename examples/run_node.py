"""
examples/run_node.py — Boot a swarm node:
  - joins the Kademlia DHT for internet-wide peer discovery
  - listens for TASK_ASSIGN messages from brain nodes (TCP port 50004)
  - launches 3 sensor agents (attendance, temperature, materials) for local use
  - aggregator subscribes to the bus and prints all incoming messages

Usage:
    python examples/run_node.py                            # standalone / no bootstrap
    python examples/run_node.py --bootstrap 192.168.1.40   # use private bootstrap node
    python examples/run_node.py --bootstrap 1.2.3.4 --port 6881
"""

import argparse
import time
import logging
import threading

from swarm.dht_discovery import start as start_discovery, get_known_nodes
from swarm.peer_server import start_server
from swarm.peer_client import exchange_with_all
from swarm.known_peers import PEER_IPS
from swarm.task_distributor import listen_for_tasks, send_result
from swarm.capability import get_capabilities
from bus.message_bus import bus
from agents.sensor_agent import SensorAgent
from core.agent_registry import get_agent_for

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)
logger = logging.getLogger("run_node")

AGGREGATOR_ID = "aggregator"

_NODE_ID = get_capabilities()["node_id"]


def aggregator_loop():
    """Receive messages addressed to the aggregator and print them."""
    logger.info("Aggregator listening on bus...")
    while True:
        msg = bus.receive(AGGREGATOR_ID, timeout=2.0)
        if msg:
            data   = msg["message"]["data"]
            sensor = data.get("sensor", "?")
            agent  = msg["message"]["agent_id"]
            if sensor == "attendance":
                print(f"[{agent}]  Attendance  — count={data['count']}  status={data['status']}", flush=True)
            elif sensor == "temperature":
                print(f"[{agent}]  Temperature — {data['celsius']}°C  humidity={data['humidity_pct']}%", flush=True)
            elif sensor == "materials":
                print(f"[{agent}]  Materials   — {data['qty']} {data['unit']} of {data['item']}", flush=True)
            else:
                print(f"[{agent}]  Unknown reading: {data}", flush=True)


def handle_task(task: dict) -> None:
    """
    Callback invoked when the brain assigns a sensor task to this worker.

    Runs in a short-lived daemon thread so it doesn't block the listener loop.
    Flow:
      1. Subscribe a one-shot inbox for this specific task.
      2. Start a SensorAgent that reports to that inbox.
      3. Wait for exactly one reading (up to 6 s).
      4. Stop the agent.
      5. Send the reading back to the brain via TCP port 50005.
    """
    threading.Thread(
        target=_execute_task,
        args=(task,),
        daemon=True,
        name=f"worker-{task.get('sensor_type', 'unk')}",
    ).start()


def _execute_task(task: dict) -> None:
    sensor_type = task.get("sensor_type", "unknown")
    task_id     = task.get("task_id", "no-id")
    brain_ip    = task.get("brain_ip", "")

    print(f"[WORKER] Starting {sensor_type} agent for remote task", flush=True)

    # Unique inbox so multiple concurrent tasks don't cross-talk
    inbox_id = f"worker-inbox-{task_id[:8]}"
    bus.subscribe(inbox_id)

    try:
        agent = get_agent_for(sensor_type, report_to=inbox_id)
    except ValueError as e:
        logger.warning("[WORKER] Cannot create agent: %s", e)
        return

    agent.start()

    # Collect the first reading (sensor fires every ~3 s; give it 6 s)
    reading = None
    deadline = time.time() + 6.0
    while time.time() < deadline:
        msg = bus.receive(inbox_id, timeout=1.0)
        if msg and msg["message"].get("type") == "sensor_reading":
            reading = msg["message"]["data"]
            break

    agent.stop()

    if reading is None:
        logger.warning("[WORKER] No reading collected for %s — skipping result send", sensor_type)
        return

    if not brain_ip:
        logger.warning("[WORKER] No brain_ip in task — cannot return result for %s", sensor_type)
        return

    send_result(
        brain_ip    = brain_ip,
        task_id     = task_id,
        sensor_type = sensor_type,
        data        = reading,
        from_node   = _NODE_ID,
    )
    print(f"[WORKER] Result sent back to brain ({brain_ip})", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Start an ANP swarm node")
    parser.add_argument(
        "--bootstrap",
        metavar="IP",
        default=None,
        help="IP of a bootstrap node to join the DHT swarm. "
             "If omitted, node starts in isolation (use static PEER_IPS for LAN).",
    )
    parser.add_argument(
        "--port",
        metavar="PORT",
        type=int,
        default=6881,
        help="UDP port of the bootstrap node (default: 6881).",
    )
    args = parser.parse_args()

    # 1. Join Kademlia DHT (internet-wide peer discovery)
    start_discovery(bootstrap_ip=args.bootstrap, bootstrap_port=args.port)
    if args.bootstrap:
        logger.info("DHT discovery started — bootstrapping from %s:%s", args.bootstrap, args.port)
    else:
        logger.info("DHT discovery started — no bootstrap, waiting for peers via static IPs")

    # Wait for DHT to populate before proceeding
    logger.info("Waiting 8 s for DHT to populate...")
    time.sleep(8)
    peers = get_known_nodes()
    if peers:
        logger.info("DHT peers found (%d): %s", len(peers), list(peers.keys()))
    else:
        logger.info("No DHT peers found yet — will keep discovering in background")

    # 1b. Start TCP peer server + connect to known peers
    start_server()
    exchange_with_all(PEER_IPS)

    # 1c. Listen for tasks assigned by brain nodes (TCP port 50004)
    listen_for_tasks(handle_task)
    logger.info("Task listener started — waiting for remote task assignments...")

    # 2. Subscribe aggregator before starting sensors (avoids race condition)
    bus.subscribe(AGGREGATOR_ID)
    agg_thread = threading.Thread(target=aggregator_loop, daemon=True, name="aggregator")
    agg_thread.start()

    # 3. Create and start local sensor agents (for this node's own monitoring)
    sensors = [
        SensorAgent("sensor-attendance",  "attendance",  report_to=AGGREGATOR_ID),
        SensorAgent("sensor-temperature", "temperature", report_to=AGGREGATOR_ID),
        SensorAgent("sensor-materials",   "materials",   report_to=AGGREGATOR_ID),
    ]
    for s in sensors:
        s.start()

    logger.info("All agents running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(10)
            peers = get_known_nodes()
            if peers:
                logger.info("Known peers: %s", list(peers.keys()))
            else:
                logger.info("No peers discovered yet.")
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
