"""
core/agent_registry.py — Maps sensor type names to instantiated SensorAgents.
"""

from agents.sensor_agent import SensorAgent

_SENSOR_TYPES = ("attendance", "temperature", "materials")

# Registry: sensor_type -> SensorAgent class (not yet instantiated)
REGISTRY: dict[str, type] = {s: SensorAgent for s in _SENSOR_TYPES}


def get_agent_for(sensor_type: str, report_to: str) -> SensorAgent:
    """
    Return an instantiated, ready-to-start SensorAgent for the given sensor type.

    Args:
        sensor_type: one of "attendance", "temperature", "materials"
        report_to:   agent_id that will receive the sensor readings

    Raises:
        ValueError if sensor_type is not in the registry
    """
    if sensor_type not in REGISTRY:
        raise ValueError(
            f"Unknown sensor type '{sensor_type}'. "
            f"Available: {list(REGISTRY.keys())}"
        )
    agent_id = f"sensor-{sensor_type}"
    return SensorAgent(agent_id=agent_id, sensor_type=sensor_type, report_to=report_to)
