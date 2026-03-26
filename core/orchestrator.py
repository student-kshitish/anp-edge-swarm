"""
core/orchestrator.py — Spawns agents for each required sensor,
collects readings from the bus for 10 seconds, and prints a summary.
"""

import time
import logging
from bus.message_bus import bus
from core.agent_registry import get_agent_for
from core.decision_agent import make_decision

logger = logging.getLogger(__name__)

ORCHESTRATOR_ID = "orchestrator"
COLLECT_SECONDS = 10


def run_intent(intent: dict, use_llm: bool = True) -> dict:
    """
    Execute an intent dict produced by parse_intent() or parse_intent_llm().

    Args:
        intent:   Structured intent dict with at least "data_required".
        use_llm:  Informational flag — records whether the intent was parsed
                  by the LLM (True) or keyword matcher (False).  The
                  orchestrator itself always works the same way regardless.

    Steps:
        1. Subscribes "orchestrator" to the bus.
        2. Spawns one SensorAgent per entry in intent["data_required"].
        3. Collects all readings for COLLECT_SECONDS seconds.
        4. Prints and returns a summary dict.
    """
    data_required: list[str] = intent.get("data_required", [])
    priority: str = intent.get("priority", "normal")
    parser_mode = "LLM" if use_llm else "keyword"

    print(f"\n[Orchestrator] Running intent — goal={intent.get('goal')}  "
          f"priority={priority}  sensors={data_required}  parser={parser_mode}")

    # Subscribe orchestrator to the bus (idempotent)
    bus.subscribe(ORCHESTRATOR_ID)

    # Spawn agents
    agents = []
    for sensor_type in data_required:
        agent = get_agent_for(sensor_type, report_to=ORCHESTRATOR_ID)
        agent.start()
        agents.append(agent)
        print(f"[Orchestrator] Started agent: {agent.agent_id}")

    # Collect readings for COLLECT_SECONDS
    print(f"\n[Orchestrator] Collecting data for {COLLECT_SECONDS}s ...\n")
    collected: dict[str, list] = {s: [] for s in data_required}
    deadline = time.time() + COLLECT_SECONDS

    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = bus.receive(ORCHESTRATOR_ID, timeout=min(1.0, remaining))
        if msg is None:
            continue
        payload = msg.get("message", {})
        if payload.get("type") != "sensor_reading":
            continue
        data = payload.get("data", {})
        sensor = data.get("sensor")
        if sensor in collected:
            collected[sensor].append(data)
            _print_reading(sensor, data)

    # Stop agents
    for agent in agents:
        agent.stop()

    # Build summary
    summary: dict[str, dict] = {}
    for sensor, readings in collected.items():
        if not readings:
            summary[sensor] = {"count": 0, "latest": None}
            continue
        summary[sensor] = {"count": len(readings), "latest": readings[-1]}

    print("\n" + "=" * 60)
    print("[Orchestrator] FINAL SUMMARY")
    print("=" * 60)
    for sensor, info in summary.items():
        print(f"  {sensor:12s} — {info['count']} readings received")
        if info["latest"]:
            print(f"               latest: {info['latest']}")
    print("=" * 60 + "\n")

    decision = make_decision(summary, intent.get("goal", "site_check"))
    print("\n" + "=" * 60)
    print("[DECISION AGENT] Assessment")
    print("=" * 60)
    print(decision)
    print("=" * 60)

    return {"summary": summary, "decision": decision}


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _print_reading(sensor: str, data: dict) -> None:
    if sensor == "attendance":
        print(f"  [sensor-attendance]  count={data['count']}  status={data['status']}")
    elif sensor == "temperature":
        print(f"  [sensor-temperature] {data['celsius']}°C  humidity={data['humidity_pct']}%")
    elif sensor == "materials":
        print(f"  [sensor-materials]   {data['qty']} {data['unit']} of {data['item']}")
    else:
        print(f"  [{sensor}] {data}")
