"""
examples/run_factory_demo.py — Demonstrates autonomous agent creation via AgentFactory.

Shows agents being spawned from an intent dict and auto-destroyed after 30 seconds
(priority="high"). Factory status is printed every 5 seconds.

Usage:
    python examples/run_factory_demo.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_factory.factory import AgentFactory

INTENT = {
    "goal": "full site check",
    "data_required": ["attendance", "temperature", "materials"],
    "priority": "high",
    "auto_spawn": True,
}

POLL_INTERVAL = 5    # seconds between status prints
TOTAL_RUNTIME = 35   # seconds — long enough to see auto-destroy fire at 30s


def main():
    print("=" * 60)
    print("  ANP-Edge Swarm — Agent Factory Demo")
    print("=" * 60)

    factory = AgentFactory()

    print(f"\n[FACTORY] Creating agents for intent: {INTENT['goal']}")
    print(f"[FACTORY] Priority: {INTENT['priority']} → auto-destroy after 30s\n")

    factory.create_from_intent(INTENT)

    print(f"\n[FACTORY] Initial status: {factory.status()}\n")

    deadline = time.time() + TOTAL_RUNTIME
    tick = 0
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        tick += POLL_INTERVAL
        status = factory.status()
        active = list(status["currently_active"].keys())
        print(f"[FACTORY] t+{tick:02d}s  total_created={status['total_created']}"
              f"  active={active}")

    print("\n[FACTORY] Final status:", factory.status())
    print("\nAll agents lifecycle complete")


if __name__ == "__main__":
    main()
