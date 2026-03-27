"""
agent_factory/registry.py — Maps capability names to agent configuration templates.
"""

AGENT_TEMPLATES: dict[str, dict] = {
    "attendance": {
        "class": "SensorAgent",
        "sensor_type": "attendance",
        "description": "Monitors worker attendance",
    },
    "temperature": {
        "class": "SensorAgent",
        "sensor_type": "temperature",
        "description": "Monitors site temperature",
    },
    "materials": {
        "class": "SensorAgent",
        "sensor_type": "materials",
        "description": "Monitors material inventory",
    },
    "vision": {
        "class": "VisionAgent",
        "sensor_type": "vision",
        "description": "Analyses images using local LLM",
    },
    "decision": {
        "class": "DecisionAgent",
        "sensor_type": "decision",
        "description": "Reasons over collected data",
    },
}


def get_template(name: str) -> dict | None:
    """Return the template dict for *name*, or None if not registered."""
    return AGENT_TEMPLATES.get(name)
