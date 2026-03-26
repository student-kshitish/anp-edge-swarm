"""
core/decision_agent.py — LLM-powered decision agent.

make_decision(summary, goal) analyses sensor readings collected by the
orchestrator and returns a human-readable assessment + recommendation.
"""

import json
import requests


def make_decision(summary: dict, goal: str) -> str:
    """
    Analyse sensor summary and return a human-readable assessment.

    Args:
        summary: dict of sensor readings produced by the orchestrator.
        goal:    original goal string from the parsed intent.

    Returns:
        A 3-5 sentence assessment string from the LLM, or a plain-text
        fallback if Ollama is unavailable.
    """
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.2:3b",
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a smart decision agent for a physical site "
                            "monitoring swarm. You receive sensor data and must give a "
                            "clear, human-readable status report in 3-5 sentences. "
                            "Be direct. Flag any problems. Give a recommendation at the end."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Goal: {goal}\n\n"
                            f"Sensor data collected:\n{json.dumps(summary, indent=2)}\n\n"
                            "Give your assessment."
                        ),
                    },
                ],
            },
        )
        return response.json()["message"]["content"]

    except Exception as e:
        print(f"[WARN] Decision agent Ollama call failed: {e}")
        return f"Decision agent unavailable. Raw data: {summary}"
