"""
core/orchestrator.py — Spawns agents for each required sensor,
collects readings from the bus for 10 seconds, merges any remote
results that arrived from worker nodes, then runs the decision agent.
"""

import time
import logging
from bus.message_bus import bus
from core.agent_registry import get_agent_for
from core.decision_agent import make_decision
from agent_factory.factory import AgentFactory
from swarm.result_collector import start_listening, wait_for_results

logger = logging.getLogger(__name__)

ORCHESTRATOR_ID = "orchestrator"
COLLECT_SECONDS = 10

factory = AgentFactory()

# Start the result-collector daemon once at import time.
# It binds UDP port 50003 and receives TASK_RESULT packets from workers.
start_listening()


def run_intent(intent: dict, use_llm: bool = True,
               remote_task_count: int = 0) -> dict:
    """
    Execute an intent dict produced by parse_intent() or parse_intent_llm().

    Args:
        intent:            Structured intent dict with at least "data_required".
        use_llm:           Informational flag (True = LLM parser, False = keyword).
        remote_task_count: Number of tasks already dispatched to remote workers.
                           The orchestrator will wait for this many TASK_RESULT
                           packets before passing data to the decision agent.
    """
    data_required: list[str] = intent.get("data_required", [])
    priority: str            = intent.get("priority", "normal")
    parser_mode              = "LLM" if use_llm else "keyword"

    print(f"\n[Orchestrator] Running intent — goal={intent.get('goal')}  "
          f"priority={priority}  sensors={data_required}  parser={parser_mode}")

    # Subscribe orchestrator to the bus (idempotent)
    bus.subscribe(ORCHESTRATOR_ID)

    # ------------------------------------------------------------------ #
    # Spawn local agents via factory
    # ------------------------------------------------------------------ #
    agents = factory.create_from_intent(intent)
    for agent in agents:
        print(f"[Orchestrator] Started agent: {agent.agent_id}")

    # ------------------------------------------------------------------ #
    # Collect local readings for COLLECT_SECONDS
    # ------------------------------------------------------------------ #
    print(f"\n[Orchestrator] Collecting local data for {COLLECT_SECONDS}s ...\n")
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
        data   = payload.get("data", {})
        sensor = data.get("sensor")
        if sensor in collected:
            collected[sensor].append(data)
            _print_reading(sensor, data)

    # Stop local agents
    for agent in agents:
        agent.stop()

    # ------------------------------------------------------------------ #
    # Wait for remote results from worker nodes
    # ------------------------------------------------------------------ #
    remote_results: list[dict] = []
    if remote_task_count > 0:
        print(f"\n[ORCHESTRATOR] Waiting for {remote_task_count} remote result(s)...")
        remote_results = wait_for_results(remote_task_count, timeout=15)
        print(f"[ORCHESTRATOR] All results collected — local + remote\n")

        # Merge remote readings into the collected dict
        for result in remote_results:
            sensor_type = result.get("sensor_type")
            data        = result.get("data", {})
            if sensor_type:
                if sensor_type not in collected:
                    collected[sensor_type] = []
                collected[sensor_type].append(data)
                print(f"  [remote] {sensor_type} from {result.get('from_node', '?')}:", end=" ")
                _print_reading(sensor_type, data)

    # ------------------------------------------------------------------ #
    # Build summary
    # ------------------------------------------------------------------ #
    summary: dict[str, dict] = {}
    for sensor, readings in collected.items():
        if not readings:
            summary[sensor] = {"count": 0, "latest": None}
        else:
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

    print(f"\n[FACTORY] Status: {factory.status()}")

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
