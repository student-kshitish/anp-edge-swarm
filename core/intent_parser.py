"""
core/intent_parser.py — Intent parsing with two strategies:

  parse_intent()     — fast keyword matching, no API, always works
  parse_intent_llm() — LLM-powered, understands any natural language,
                       falls back to parse_intent() on any error

  Responses are cached for _cache_ttl seconds to avoid redundant Ollama calls.
"""

import json
import time
import logging
import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

ALL_SENSORS = ["attendance", "temperature", "materials"]

KEYWORDS = {
    "attendance":   ["attendance", "headcount", "people", "workers", "staff"],
    "temperature":  ["temperature", "temp", "heat", "celsius", "humidity"],
    "materials":    ["materials", "inventory", "stock", "items", "supplies"],
}

_SYSTEM_PROMPT = """\
You are an intent parser for a construction-site monitoring swarm.
Given a user request, return ONLY a valid JSON object with these exact fields:

{
  "goal":          "<one short phrase describing what the user wants>",
  "data_required": ["<sensor_type>", ...],
  "priority":      "high" or "normal",
  "location":      "<location string if mentioned, or null>",
  "auto_spawn":    true
}

Valid sensor types (use ONLY these exact strings):
  "attendance"   — headcount / people present
  "temperature"  — temperature and humidity readings
  "materials"    — inventory / stock levels

Rules:
- If the user mentions "all", or asks a general "how is the site" style question,
  include all three sensors in data_required.
- If the user says urgent / critical / now / immediately, set priority to "high".
- Return ONLY the JSON object — no markdown, no explanation, no extra text.
"""

# Shared session — reuses TCP connections across calls
_session = requests.Session()

# ------------------------------------------------------------------ #
# Response cache
# ------------------------------------------------------------------ #
_cache: dict = {}
_cache_ttl: int = 60   # seconds


# ------------------------------------------------------------------ #
# LLM-powered parser
# ------------------------------------------------------------------ #

def parse_intent_llm(user_text: str) -> dict:
    """
    Parse user text into a structured intent dict using Ollama (local LLM).

    Cached for _cache_ttl seconds — repeated identical queries skip Ollama.
    Falls back to keyword-based parse_intent() if the API call fails.
    """
    # Normalise cache key so "Check Temp" and "check temp" are the same
    cache_key = " ".join(user_text.lower().split())

    if cache_key in _cache:
        if time.time() - _cache[cache_key]["ts"] < _cache_ttl:
            print("[INTENT] Cache hit - skipping Ollama call")
            return _cache[cache_key]["result"]

    try:
        response = _session.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an intent parser for an edge sensor swarm system. "
                            "You must return ONLY a raw JSON object. No markdown. No explanation. "
                            "No backticks. Just the JSON. "
                            'Format: {"goal": "what user wants", "data_required": ["sensors needed"], '
                            '"priority": "high or normal", "location": "location or null", "auto_spawn": true}. '
                            "Valid sensor values: attendance, temperature, materials only. "
                            "If user mentions site, all, or everything — include all three. "
                            "If unsure — include all three."
                        ),
                    },
                    {
                        "role": "user",
                        "content": user_text,
                    },
                ],
            },
            timeout=30,
        )

        content = response.json()["message"]["content"].strip()

        # Strip markdown fences if present
        if content.startswith("```"):
            parts = content.split("```")
            # parts[1] is the fenced block; strip optional "json" language tag
            content = parts[1].lstrip("json").strip() if len(parts) > 1 else content

        # Find the outermost JSON object
        start = content.find("{")
        end   = content.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in LLM response")
        intent = json.loads(content[start:end])

        print("Parsed intent (LLM):", json.dumps(intent, indent=2))
        _cache[cache_key] = {"result": intent, "ts": time.time()}
        return intent

    except Exception as e:
        print(f"[WARN] Ollama failed: {e} — using keyword fallback")
        return parse_intent(user_text)


# ------------------------------------------------------------------ #
# Keyword-based parser (original, kept intact)
# ------------------------------------------------------------------ #

def parse_intent(user_text: str) -> dict:
    """
    Parse plain English into a structured intent dict using keyword matching.
    """
    text = user_text.lower()

    if "all" in text.split():
        data_required = list(ALL_SENSORS)
    else:
        data_required = [
            sensor
            for sensor, kws in KEYWORDS.items()
            if any(kw in text for kw in kws)
        ]

    priority = "high" if any(
        w in text for w in ("urgent", "critical", "now", "immediately")
    ) else "normal"

    intent = {
        "goal": "site_check",
        "data_required": data_required if data_required else list(ALL_SENSORS),
        "priority": priority,
        "auto_spawn": True,
    }

    print("Parsed intent (keyword):", json.dumps(intent, indent=2))
    return intent
