"""
examples/run_node.py — Boot a swarm node:
  - starts UDP discovery
  - launches 3 sensor agents (attendance, temperature, materials)
  - aggregator subscribes to the bus and prints all incoming messages
"""

import time
import logging
import threading

from swarm.discovery import start as start_discovery, get_known_nodes
from bus.message_bus import bus
from agents.sensor_agent import SensorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)
logger = logging.getLogger("run_node")

AGGREGATOR_ID = "aggregator"


def aggregator_loop():
    """Receive messages addressed to the aggregator and print them."""
    logger.info("Aggregator listening on bus...")
    while True:
        msg = bus.receive(AGGREGATOR_ID, timeout=2.0)
        if msg:
            data = msg["message"]["data"]
            sensor = data.get("sensor", "?")
            agent = msg["message"]["agent_id"]
            # Pretty-print based on sensor type
            if sensor == "attendance":
                print(f"[{agent}]  Attendance  — count={data['count']}  status={data['status']}", flush=True)
            elif sensor == "temperature":
                print(f"[{agent}]  Temperature — {data['celsius']}°C  humidity={data['humidity_pct']}%", flush=True)
            elif sensor == "materials":
                print(f"[{agent}]  Materials   — {data['qty']} {data['unit']} of {data['item']}", flush=True)
            else:
                print(f"[{agent}]  Unknown reading: {data}", flush=True)


def main():
    # 1. Start UDP discovery
    start_discovery()
    logger.info("UDP discovery started — listening for peers...")

    # 2. Subscribe aggregator before starting sensors (avoids race condition)
    bus.subscribe(AGGREGATOR_ID)
    agg_thread = threading.Thread(target=aggregator_loop, daemon=True, name="aggregator")
    agg_thread.start()

    # 3. Create and start sensor agents
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
