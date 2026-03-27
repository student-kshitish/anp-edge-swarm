"""
agent_factory/factory.py — Creates and manages agents from parsed intents.
"""

import logging
from uuid import uuid4

from agent_factory.registry import get_template
from agent_factory.lifecycle import AgentLifecycle
from agents.sensor_agent import SensorAgent

logger = logging.getLogger(__name__)

_AUTO_DESTROY_HIGH = 30    # seconds for "high" priority intents
_AUTO_DESTROY_NORMAL = 60  # seconds for everything else


class AgentFactory:
    def __init__(self):
        self.lifecycle = AgentLifecycle()
        self.created_count = 0

    def create_from_intent(self, intent: dict) -> list:
        """
        Instantiate and spawn one agent per entry in intent["data_required"].

        Returns the list of spawned agent objects.
        """
        data_required: list[str] = intent.get("data_required", [])
        priority: str = intent.get("priority", "normal")
        ttl = _AUTO_DESTROY_HIGH if priority == "high" else _AUTO_DESTROY_NORMAL

        spawned = []
        for sensor_type in data_required:
            template = get_template(sensor_type)
            if template is None:
                print(f"[FACTORY] WARNING: no template for '{sensor_type}' — skipping",
                      flush=True)
                continue

            agent_id = f"{sensor_type}-agent-{uuid4().hex[:6]}"

            # Only SensorAgent is instantiable right now; other classes are
            # placeholders in the registry (VisionAgent, DecisionAgent).
            if template["class"] != "SensorAgent":
                print(f"[FACTORY] WARNING: '{template['class']}' not yet implemented "
                      f"— skipping '{sensor_type}'", flush=True)
                continue

            agent = SensorAgent(
                agent_id=agent_id,
                sensor_type=sensor_type,
                report_to="orchestrator",
            )

            self.lifecycle.spawn(agent_id, agent)
            self.lifecycle.auto_destroy_after(agent_id, ttl)
            self.created_count += 1
            spawned.append(agent)

        return spawned

    def status(self) -> dict:
        return {
            "total_created": self.created_count,
            "currently_active": self.lifecycle.status(),
        }
