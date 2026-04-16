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

# Interval between ML pipeline runs after a successful cycle (seconds)
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
        self._log_offset  = 0   # tracks how far into bus.get_log() we've consumed

    def start(self):
        self.running = True
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
        """
        Drain new sensor_reading messages from the shared bus log.
        Uses an offset so each entry is processed exactly once.
        """
        while self.running:
            try:
                bus = self.get_bus()
                log = bus.get_log()
                new_entries = log[self._log_offset:]
                self._log_offset += len(new_entries)

                for entry in new_entries:
                    msg = entry.get("message", {})
                    if isinstance(msg, dict) and msg.get("type") == "sensor_reading":
                        data = msg.get("data", {})
                        if data:
                            self.buffer.add(data)
            except Exception:
                pass
            time.sleep(1)

    def _pipeline_loop(self):
        while self.running:
            try:
                if self.buffer.is_ready():
                    self.cycle_count += 1
                    print(f"[PIPELINE] Auto-triggering cycle {self.cycle_count}")

                    window = self.buffer.get_window()
                    peers  = self.get_peers()

                    # Build latest per-sensor dict from the last 3 readings
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

                    time.sleep(_PIPELINE_COOLDOWN)
                else:
                    time.sleep(2)
            except Exception as e:
                print(f"[PIPELINE] Error: {e}")
                time.sleep(5)

    def stop(self):
        self.running = False
