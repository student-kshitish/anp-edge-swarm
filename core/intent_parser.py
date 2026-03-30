"""
core/intent_parser.py — Intent parsing with two strategies:

  parse_intent()     — fast keyword matching, no API, always works
  parse_intent_llm() — Claude-powered, understands any natural language,
                       falls back to parse_intent() on any error

  Responses are cached for _cache_ttl seconds to avoid redundant Ollama calls.
"""

import json
import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

ALL_SENSORS = ["attendance", "temperature", "materials"]

KEYWORDS = {
    "attendance":   ["attendance", "headcount", "people", "workers", "staff"],
    "temperature":  ["temperature", "temp", "heat", "celsius", "humidity"],
    "materials":    ["materials", "inventory", "stock", "items", "supplies"],
}

# System prompt for the LLM parser
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

# ------------------------------------------------------------------ #
# Response cache (FIX 7)
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
    cache_key = user_text.strip().lower()

    # Cache hit — skip Ollama entirely
    if cache_key in _cache:
        if time.time() - _cache[cache_key]["ts"] < _cache_ttl:
            print("[INTENT] Cache hit - skipping Ollama call")
            return _cache[cache_key]["result"]

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
        )

        content = response.json()["message"]["content"]

        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        intent = json.loads(content)
        print("Parsed intent (LLM):", json.dumps(intent, indent=2))

        # Store in cache
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

    Example:
        parse_intent("check attendance and temperature at site")
        -> {
            "goal": "site_check",
            "data_required": ["attendance", "temperature"],
            "priority": "normal",
            "auto_spawn": True
           }
    """
    text = user_text.lower()

    # "all" shortcut
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
