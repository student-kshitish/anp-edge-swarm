"""
core/orchestrator.py — Spawns agents for each required sensor,
collects readings from the bus adaptively, merges any remote
results from worker nodes, then runs the ML pipeline distributed
across known swarm nodes, and passes the assembled result to the
decision agent (non-blocking).
"""

import time
import threading
import logging
from bus.message_bus import bus
from core.decision_agent import make_decision
from agent_factory.factory import AgentFactory
from swarm.result_collector import start_listening, wait_for_results
from ml.stream_buffer import StreamBuffer
from ml.task_decomposer import TaskDecomposer
from ml.parallel_executor import ParallelExecutor
from ml.result_assembler import ResultAssembler
from ml.inference_server import start_server as start_inference_server
from agents.action_agent import ActionAgent
from db.store import save_sensor_reading
from db.schema import init_db
from db.db_agent_singleton import get_db
from swarm.node_identity import get_node_id

logger = logging.getLogger(__name__)

# Initialise the local SQLite database once at import time.
init_db()

ORCHESTRATOR_ID = "orchestrator"

# Adaptive collection parameters
_TARGET_PER_SENSOR = 3   # minimum readings per sensor type
_MAX_WAIT          = 10.0
_MIN_WAIT          = 3.0
_POLL_INTERVAL     = 0.1

factory = AgentFactory()

# Sliding window buffer — shared across calls
stream_buffer = StreamBuffer(maxlen=50)

# Start the result-collector daemon once at import time.
# It binds UDP port 50003 and receives TASK_RESULT packets from workers.
start_listening()

# Start the inference TCP server so this node can accept remote task requests.
start_inference_server()


def run_intent(intent: dict, use_llm: bool = True,
               remote_task_count: int = 0,
               user_text: str = None,
               start_time: float = None) -> dict:
    """
    Execute an intent dict, optionally overlapping LLM parsing with
    sensor collection for reduced end-to-end latency.

    Args:
        intent:            Structured intent dict (from parse_intent or parse_intent_llm).
        use_llm:           If True and user_text is provided, LLM parse runs in parallel
                           with sensor collection.
        remote_task_count: Number of tasks dispatched to remote workers to wait for.
        user_text:         Raw user query. When provided, LLM parsing is run in a
                           background thread overlapping with sensor collection (FIX 2).
        start_time:        time.time() from the caller; used to print [TIMER] lines.
    """
    _t0 = start_time  # may be None — only print timers when provided

    # ------------------------------------------------------------------ #
    # FIX 2: start LLM parse in background; use keyword parse for agents
    # ------------------------------------------------------------------ #
    _llm_intent: list = [None]
    _llm_thread: threading.Thread | None = None

    if user_text and use_llm:
        from core.intent_parser import parse_intent, parse_intent_llm

        def _parse_llm():
            try:
                _llm_intent[0] = parse_intent_llm(user_text)
            except Exception:
                pass

        _llm_thread = threading.Thread(target=_parse_llm, daemon=True,
                                       name="llm-intent-parser")
        _llm_thread.start()

        # Immediately derive agents from fast keyword parse
        fast_intent = parse_intent(user_text)
        intent = fast_intent

    data_required: list[str] = intent.get("data_required", [])
    priority: str             = intent.get("priority", "normal")
    parser_mode               = "LLM+parallel" if _llm_thread else ("LLM" if use_llm else "keyword")

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
    if _t0:
        print(f"[TIMER] Agents started in {time.time() - _t0:.2f}s")

    # ------------------------------------------------------------------ #
    # FIX 1: adaptive collection
    # ------------------------------------------------------------------ #
    target_readings = max(len(data_required) * _TARGET_PER_SENSOR, 1)
    print(f"\n[Orchestrator] Collecting "
          f"(target={target_readings} readings, min={_MIN_WAIT}s, max={_MAX_WAIT}s) ...\n")

    collected: dict[str, list] = {s: [] for s in data_required}
    t_collect_start = time.time()
    deadline        = t_collect_start + _MAX_WAIT

    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = bus.receive(ORCHESTRATOR_ID, timeout=min(_POLL_INTERVAL, remaining))

        elapsed       = time.time() - t_collect_start
        total_so_far  = sum(len(v) for v in collected.values())

        if msg is not None:
            payload = msg.get("message", {})
            if payload.get("type") == "sensor_reading":
                data   = payload.get("data", {})
                sensor = data.get("sensor")
                if sensor in collected:
                    collected[sensor].append(data)
                    _print_reading(sensor, data)
                    total_so_far = sum(len(v) for v in collected.values())
                    try:
                        save_sensor_reading(
                            sensor_type=sensor,
                            raw_data=data,
                            node_id=get_node_id(),
                        )
                    except Exception:
                        pass
                    try:
                        db = get_db()
                        db.save_sensor_reading(sensor, data)
                    except Exception:
                        pass

        # Early-exit: min time elapsed AND enough readings gathered
        if elapsed >= _MIN_WAIT and total_so_far >= target_readings:
            break

    elapsed_collect = time.time() - t_collect_start
    total_collected = sum(len(v) for v in collected.values())
    print(f"[ORCHESTRATOR] Collected {total_collected} readings in {elapsed_collect:.1f}s")
    if _t0:
        print(f"[TIMER] Sensors collected in {time.time() - _t0:.2f}s")

    # Stop local agents
    for agent in agents:
        agent.stop()

    # If LLM parse finished by now, upgrade intent for goal/priority context
    if _llm_thread is not None:
        _llm_thread.join(timeout=0)  # non-blocking check
        if _llm_intent[0] is not None:
            intent = _llm_intent[0]
            # Ensure collected dict covers any additional sensors from LLM parse
            for s in intent.get("data_required", []):
                if s not in collected:
                    collected[s] = []

    # Feed every collected reading into the sliding window buffer
    for readings in collected.values():
        for reading in readings:
            stream_buffer.add(reading)

    # ------------------------------------------------------------------ #
    # Wait for remote results from worker nodes
    # ------------------------------------------------------------------ #
    remote_results: list[dict] = []
    if remote_task_count > 0:
        print(f"\n[ORCHESTRATOR] Waiting for {remote_task_count} remote result(s)...")
        remote_results = wait_for_results(remote_task_count, timeout=15)
        print(f"[ORCHESTRATOR] All results collected — local + remote\n")

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
    # Build raw summary (for logging / decision agent fallback)
    # ------------------------------------------------------------------ #
    summary: dict[str, dict] = {}
    for sensor, readings in collected.items():
        if not readings:
            summary[sensor] = {"count": 0, "latest": None}
        else:
            summary[sensor] = {"count": len(readings), "latest": readings[-1]}

    print("\n" + "=" * 60)
    print("[Orchestrator] SENSOR SUMMARY")
    print("=" * 60)
    for sensor, info in summary.items():
        print(f"  {sensor:12s} — {info['count']} readings received")
        if info["latest"]:
            print(f"               latest: {info['latest']}")
    print("=" * 60 + "\n")

    # ------------------------------------------------------------------ #
    # ML Pipeline — distribute tasks across swarm nodes
    # ------------------------------------------------------------------ #
    latest_readings: dict = {}
    for sensor, info in summary.items():
        if info["latest"]:
            latest_readings.update(info["latest"])

    try:
        from swarm.peer_server import get_known_nodes
        known = get_known_nodes()
    except Exception:
        try:
            from swarm.peer_discovery import get_known_nodes
            known = get_known_nodes()
        except Exception:
            known = {}

    final: dict = {}
    if latest_readings:
        decomposer = TaskDecomposer()
        executor   = ParallelExecutor()
        assembler  = ResultAssembler()

        plan = decomposer.decompose(latest_readings, known)
        print("[ML] Task plan:", {t: a["node_id"] for t, a in plan.items()})

        window     = stream_buffer.get_window()
        ml_results = executor.execute(plan, latest_readings, window)

        print("\n" + "=" * 60)
        print("[ML] PIPELINE RESULTS")
        print("=" * 60)
        final = assembler.assemble(ml_results)
        print("=" * 60 + "\n")

        try:
            get_db().save_prediction(final)
        except Exception:
            pass

    if _t0:
        print(f"[TIMER] ML pipeline done in {time.time() - _t0:.2f}s")

    # ------------------------------------------------------------------ #
    # FIX 3: run decision agent in background — do not block return
    # ------------------------------------------------------------------ #
    _goal = intent.get("goal", "site_check")
    _decision_input = final if final else summary

    result = {"summary": summary, "ml_pipeline": final, "decision": "computing..."}

    def _run_decision():
        d = make_decision(_decision_input, _goal)
        print("\n" + "=" * 60)
        print("[DECISION AGENT] Assessment")
        print("=" * 60)
        print(d)
        print("=" * 60)
        if _t0:
            print(f"[TIMER] Decision done in {time.time() - _t0:.2f}s")

        try:
            action_agent = ActionAgent()
            action_result = action_agent.execute(
                _decision_input,
                summary
            )
            print(f"[ACTION] Actions taken: {action_result['actions_taken']}")
            result["action"] = action_result
        except Exception as e:
            import traceback
            print(f"[ACTION] Error: {e}")
            traceback.print_exc()

    threading.Thread(target=_run_decision, daemon=False,
                     name="decision-agent").start()
    time.sleep(0.1)  # give thread time to start

    print(f"\n[FACTORY] Status: {factory.status()}")

    return result


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
