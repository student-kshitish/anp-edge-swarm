"""
examples/run_intent.py — Interactive demo for the intent → agent pipeline.

Uses the LLM-powered parser (Claude) to understand any natural language.
Falls back to keyword matching if the API key is not set.

Usage:
    python examples/run_intent.py

Example queries:
    "check attendance and temperature"
    "how many workers are on site right now?"
    "is the warehouse running low on materials?"
    "full site check — urgent"
    "check all sensors"
"""

import sys
import os
import logging
import time

# Allow imports from project root regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env before importing project modules so the API key is available
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
))

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)-7s  %(name)s — %(message)s",
)

from core.intent_parser import parse_intent_llm
from core.orchestrator import run_intent
from swarm.dht_discovery import start as start_discovery
from swarm.peer_server import start_server
from swarm.peer_client import exchange_with_all
from swarm.known_peers import PEER_IPS
from swarm.task_distributor import distribute_tasks


def main():
    print("=" * 60)
    print("  ANP-Edge Swarm — LLM Intent Orchestrator")
    print("=" * 60)

    # Start discovery and TCP peer exchange so we can see peers
    start_discovery()
    start_server()
    exchange_with_all(PEER_IPS)
    print("[PEER] Waiting for peer connections...")
    time.sleep(5)

    user_text = input("\nWhat do you want to check? ").strip()
    if not user_text:
        print("No input provided. Exiting.")
        return

    # 1. Parse with Claude (falls back to keywords automatically)
    print()
    intent = parse_intent_llm(user_text)

    # 2. Distribute tasks across swarm nodes
    print("\n[SWARM] Distributing tasks...")
    plan = distribute_tasks(intent)
    print(f"[SWARM] Local tasks:  {plan['local_tasks']}")
    print(f"[SWARM] Remote tasks: {plan['remote_tasks']}")

    # Count how many sensor tasks were sent to remote workers
    remote_count = sum(len(v) for v in plan["remote_tasks"].values())

    # 3. Run orchestrator for local tasks; it will wait for remote results too
    local_intent = dict(intent)
    local_intent["data_required"] = plan["local_tasks"]

    if not plan["local_tasks"] and remote_count == 0:
        print("\n[SWARM] No tasks to run — exiting.")
        return

    result = run_intent(local_intent, use_llm=True, remote_task_count=remote_count)

    # 4. Print the returned summary dict
    print("Returned summary dict:")
    for sensor, info in result["summary"].items():
        print(f"  {sensor}: {info['count']} reading(s), latest={info['latest']}")


if __name__ == "__main__":
    main()
