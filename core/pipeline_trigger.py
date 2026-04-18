"""
core/pipeline_trigger.py — Watches the shared message bus log and triggers
the ML pipeline automatically when enough sensor readings accumulate.
No human input needed.
"""

import threading
import time
from ml.stream_buffer import StreamBuffer
from ml.task_decomposer import TaskDecomposer
from ml.parallel_executor import ParallelExecutor
from ml.result_assembler import ResultAssembler
from agents.action_agent import ActionAgent

# Default interval between ML pipeline runs (seconds).
# Overridden at runtime by GoalManager.get_recommended_interval().
_PIPELINE_COOLDOWN = 30


class PipelineTrigger:

    def __init__(self, get_peers_fn, get_bus_fn):
        self.get_peers    = get_peers_fn
        self.get_bus      = get_bus_fn
        self.buffer       = StreamBuffer(maxlen=50)
        self.decomposer   = TaskDecomposer()
        self.executor     = ParallelExecutor()
        self.assembler    = ResultAssembler()
        self.action_agent = ActionAgent()
        self.running      = False
        self.cycle_count  = 0
        # Set by SwarmMind after construction to avoid circular import.
        self.mind         = None

    def start(self):
        self.running = True
        # Subscribe to message bus (legacy path — keeps existing behaviour)
        from bus.message_bus import bus as _bus
        _bus.subscribe("swarm-mind")
        # Subscribe to event bus (event-driven path — no polling required)
        from bus.event_bus import get_event_bus
        get_event_bus().subscribe(
            "sensor.reading",
            self._on_sensor_event,
            agent_id="pipeline-trigger",
        )
        threading.Thread(
            target=self._collect_loop,
            daemon=True,
            name="pipeline-trigger-collect",
        ).start()
        threading.Thread(
            target=self._pipeline_loop,
            daemon=True,
            name="pipeline-trigger-ml",
        ).start()
        print("[PIPELINE] Auto pipeline trigger started")

    def feed(self, reading: dict):
        """Directly inject a sensor reading into the buffer."""
        self.buffer.add(reading)

    def _collect_loop(self):
        from bus.message_bus import bus
        while self.running:
            try:
                envelope = bus.receive("swarm-mind", timeout=1)
                if envelope:
                    payload = envelope.get("message", {})
                    if isinstance(payload, dict) and payload.get("type") == "sensor_reading":
                        data = payload.get("data", {})
                        if data:
                            self.buffer.add(data)
                            print(
                                f"[PIPELINE] Reading buffered: "
                                f"{data.get('sensor', '?')} "
                                f"buffer={len(self.buffer._data)}"
                            )
                            try:
                                from db.db_agent_singleton import get_db
                                sensor_type = data.get("sensor", "unknown")
                                get_db().save_sensor_reading(sensor_type, data)
                            except Exception:
                                pass
            except Exception:
                pass

    def _pipeline_loop(self):
        while self.running:
            try:
                if self.buffer.is_ready():
                    self.cycle_count += 1
                    print(f"[PIPELINE] Auto-triggering cycle {self.cycle_count}")

                    window = self.buffer.get_window()
                    peers  = self.get_peers()

                    latest: dict = {}
                    for reading in window[-3:]:
                        sensor = reading.get("sensor")
                        if sensor:
                            latest[sensor] = reading

                    if not latest:
                        time.sleep(5)
                        continue

                    plan    = self.decomposer.decompose(latest, peers)
                    results = self.executor.execute(plan, latest, window)
                    final   = self.assembler.assemble(results)

                    self.action_agent.execute(final, latest)

                    print(
                        f"[PIPELINE] Cycle {self.cycle_count} complete "
                        f"— status={final.get('status', '?')}"
                    )

                    # Record decision for self-improvement learning
                    try:
                        if self.mind is not None:
                            decision_id = f"dec_{int(time.time())}_{self.cycle_count}"
                            contributing = [
                                v["node_id"] for v in plan.values()
                                if isinstance(v, dict) and "node_id" in v
                            ]
                            self.mind.improvement.record_decision(
                                decision_id=decision_id,
                                decision_type="ml_pipeline",
                                inputs={
                                    "anomaly_count": len(
                                        final.get("anomalies_found", [])),
                                    "urgency":       final.get(
                                        "action_urgency", "LOW"),
                                    "status":        final.get("status", "OK"),
                                    "contributing_nodes": contributing,
                                },
                                action_taken=final,
                            )

                            # Reflective decision — appended to final for downstream use
                            decision = self.mind.reflection.reflect_and_decide(
                                current_input=final,
                                historical_data=self.mind.improvement.decision_history[-50:],
                            )
                            final["reflective_decision"] = decision
                    except Exception:
                        pass

                    # Use goal manager's recommended interval if available
                    interval = (
                        self.mind.goals.get_recommended_interval()
                        if self.mind is not None
                        else _PIPELINE_COOLDOWN
                    )
                    time.sleep(interval)
                else:
                    time.sleep(2)
            except Exception as e:
                print(f"[PIPELINE] Error: {e}")
                time.sleep(5)

    def _on_sensor_event(self, event: dict):
        """EventBus callback — ingest sensor readings published by any agent."""
        reading = event.get("data", {})
        if isinstance(reading, dict) and reading:
            self.buffer.add(reading)

    def stop(self):
        self.running = False
