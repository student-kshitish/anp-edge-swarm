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
from swarm.discovery import start as start_discovery
from swarm.task_distributor import distribute_tasks


def main():
    print("=" * 60)
    print("  ANP-Edge Swarm — LLM Intent Orchestrator")
    print("=" * 60)

    # Start discovery so we can see peers before distributing tasks
    start_discovery()

    user_text = input("\nWhat do you want to check? ").strip()
    if not user_text:
        print("No input provided. Exiting.")
        return

    # 1. Parse with Claude (falls back to keywords automatically)
    print()
    intent = parse_intent_llm(user_text)

    # 2. Distribute tasks across swarm nodes
    plan = distribute_tasks(intent)
    print(f"\n[SWARM] Local tasks:  {plan['local_tasks']}")
    print(f"[SWARM] Remote tasks: {plan['remote_tasks']}")

    # 3. Run orchestrator for local tasks only
    local_intent = dict(intent)
    local_intent["data_required"] = plan["local_tasks"]

    if not plan["local_tasks"]:
        print("\n[SWARM] All tasks offloaded to remote nodes — nothing to run locally.")
        return

    result = run_intent(local_intent, use_llm=True)

    # 4. Print the returned summary dict
    print("Returned summary dict:")
    for sensor, info in result["summary"].items():
        print(f"  {sensor}: {info['count']} reading(s), latest={info['latest']}")


if __name__ == "__main__":
    main()
