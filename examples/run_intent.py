"""
examples/run_intent.py — Interactive demo for the intent → agent pipeline.

Uses the LLM-powered parser (Ollama) to understand any natural language.
Falls back to keyword matching if Ollama is unavailable.

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

from core.intent_parser import parse_intent
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

    # Start overall timer
    t0 = time.time()

    # FIX 2: Use fast keyword parse for swarm distribution (instant, no Ollama).
    # The orchestrator will run the LLM parse in parallel with sensor collection.
    print()
    intent = parse_intent(user_text)
    print(f"[TIMER] Intent parsed in {time.time() - t0:.2f}s")

    # Distribute tasks across swarm nodes
    print("\n[SWARM] Distributing tasks...")
    plan = distribute_tasks(intent)
    print(f"[SWARM] Local tasks:  {plan['local_tasks']}")
    print(f"[SWARM] Remote tasks: {plan['remote_tasks']}")

    remote_count = sum(len(v) for v in plan["remote_tasks"].values())

    # Run orchestrator — LLM parsing overlaps with sensor collection inside
    local_intent = dict(intent)
    local_intent["data_required"] = plan["local_tasks"]

    if not plan["local_tasks"] and remote_count == 0:
        print("\n[SWARM] No tasks to run — exiting.")
        return

    result = run_intent(
        local_intent,
        use_llm=True,
        remote_task_count=remote_count,
        user_text=user_text,
        start_time=t0,
    )

    # Print returned summary
    print("Returned summary dict:")
    for sensor, info in result["summary"].items():
        print(f"  {sensor}: {info['count']} reading(s), latest={info['latest']}")

    print(f"[TIMER] TOTAL end-to-end: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
