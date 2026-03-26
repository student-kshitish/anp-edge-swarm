"""
agents/sensor_agent.py — SensorAgent that simulates three sensor types
and forwards readings to a configured report_to agent every 3 seconds.
"""

import time
import random
import logging
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

SENSOR_TYPES = ("attendance", "temperature", "materials")


class SensorAgent(BaseAgent):
    def __init__(self, agent_id: str, sensor_type: str, report_to: str):
        if sensor_type not in SENSOR_TYPES:
            raise ValueError(f"sensor_type must be one of {SENSOR_TYPES}")
        super().__init__(agent_id=agent_id, role="sensor")
        self.sensor_type = sensor_type
        self.report_to = report_to

    # ------------------------------------------------------------------ #
    # Simulated readings
    # ------------------------------------------------------------------ #

    def _read(self) -> dict:
        if self.sensor_type == "attendance":
            return {
                "sensor": "attendance",
                "count": random.randint(0, 50),
                "status": random.choice(["present", "absent", "unknown"]),
            }
        if self.sensor_type == "temperature":
            return {
                "sensor": "temperature",
                "celsius": round(random.uniform(18.0, 35.0), 1),
                "humidity_pct": round(random.uniform(30.0, 80.0), 1),
            }
        # materials
        return {
            "sensor": "materials",
            "item": random.choice(["bolt", "panel", "wire", "pipe"]),
            "qty": random.randint(1, 100),
            "unit": "pcs",
        }

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #

    def run(self):
        while self._running:
            reading = self._read()
            payload = {
                "type": "sensor_reading",
                "agent_id": self.agent_id,
                "data": reading,
                "ts": time.time(),
            }
            sent = self.send(self.report_to, payload)
            logger.debug("[%s] sent reading to %s (ok=%s): %s",
                         self.agent_id, self.report_to, sent, reading)
            time.sleep(3)
