"""
ml/model_hierarchy.py — Three-tier inference hierarchy.

Tier 1 (sensor)  — pure Python math; runs on any device including phones.
                   Sub-5ms latency. Threshold checks, moving averages, FFT.
Tier 2 (edge)    — lightweight inference (≤500M params); typical edge node.
                   50–200ms latency. Trend analysis, pattern matching.
Tier 3 (brain)   — full LLM reasoning (3B+ params); only on capable nodes.
                   500ms–5s latency. Action planning, natural language.

Routing ensures heavier tasks only travel to nodes that can actually run them,
preventing wasted inference time and network round-trips for trivial work.
"""

import math
import time

from swarm.node_identity import get_node_id


class ModelHierarchy:
    """Detects this node's inference tier and routes tasks accordingly."""

    LEVELS = {
        1: {
            "name":       "sensor",
            "desc":       "Event detection — FFT, threshold, simple stats",
            "max_params": "0",
            "latency":    "1-5ms",
            "functions":  [
                "threshold_check", "moving_average",
                "fft_peak_detect", "simple_anomaly",
            ],
        },
        2: {
            "name":       "edge",
            "desc":       "Initial reasoning — lightweight inference",
            "max_params": "500M",
            "latency":    "50-200ms",
            "functions":  [
                "trend_analysis", "pattern_match",
                "classification", "clustering",
            ],
        },
        3: {
            "name":       "brain",
            "desc":       "Deep reasoning — full LLM inference",
            "max_params": "3B+",
            "latency":    "500ms-5s",
            "functions":  [
                "action_planning", "context_reasoning",
                "natural_language", "decision_making",
            ],
        },
    }

    # Maps each swarm task type to the minimum tier required to run it
    _TASK_TIER = {
        "clean":   1,
        "anomaly": 1,
        "trend":   2,
        "history": 2,
        "action":  3,
    }

    def __init__(self, node_level: int = None):
        self.level = node_level if node_level else self._detect_level()
        info = self.LEVELS[self.level]
        print(
            f"[HIERARCHY] Node level: {self.level} "
            f"({info['name']}) — {info['desc']}"
        )

    # ------------------------------------------------------------------
    # Auto-detection
    # ------------------------------------------------------------------

    def _detect_level(self) -> int:
        try:
            import psutil
            ram = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            ram = 1.0

        try:
            import requests
            r = requests.get("http://localhost:11434/api/tags", timeout=2)
            has_llm = len(r.json().get("models", [])) > 0
        except Exception:
            has_llm = False

        if has_llm and ram >= 8:
            return 3
        if ram >= 4:
            return 2
        return 1

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def can_handle(self, task_type: str) -> bool:
        """Return True if this node's tier is sufficient for *task_type*."""
        return self.level >= self._TASK_TIER.get(task_type, 3)

    def route_task(self, task_type: str, known_nodes: dict) -> str:
        """
        Return the node_id best suited to run *task_type*.

        Prefers this node if capable. Otherwise picks the first peer that
        satisfies the tier requirement based on benchmark data.
        Falls back to local node if no suitable peer is found.
        """
        required = self._TASK_TIER.get(task_type, 3)

        if self.level >= required:
            return get_node_id()

        for nid, info in known_nodes.items():
            caps  = info.get("caps", info)
            bench = caps.get("benchmark", {})
            if required == 3 and bench.get("llm_available"):
                return nid
            if required == 2 and bench.get("composite", 0) > 20:
                return nid

        return get_node_id()

    # ------------------------------------------------------------------
    # Tier 1 — pure Python, no external dependencies
    # ------------------------------------------------------------------

    @staticmethod
    def threshold_check(value: float, low: float, high: float) -> dict:
        """Return an alert dict if *value* is outside [low, high]."""
        if value < low:
            return {"alert": True,  "direction": "LOW",  "deviation": low  - value}
        if value > high:
            return {"alert": True,  "direction": "HIGH", "deviation": value - high}
        return {"alert": False}

    @staticmethod
    def moving_average(window: list, field: str) -> float:
        """Compute the mean of *field* across *window* readings."""
        values = [
            r.get(field, 0) for r in window if r.get(field) is not None
        ]
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def simple_anomaly(value: float, window: list, field: str) -> dict:
        """Z-score anomaly detection against the window mean for *field*."""
        values = [
            r.get(field, 0) for r in window if r.get(field) is not None
        ]
        if len(values) < 3:
            return {"anomaly": False}
        mean = sum(values) / len(values)
        std  = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        if std == 0:
            return {"anomaly": False}
        z_score = abs(value - mean) / std
        return {
            "anomaly":  z_score > 2.5,
            "z_score":  round(z_score,  2),
            "mean":     round(mean,      2),
            "std":      round(std,       2),
            "severity": (
                "HIGH"   if z_score > 3.0 else
                "MEDIUM" if z_score > 2.5 else
                "LOW"
            ),
        }

    @staticmethod
    def fft_peak_detect(values: list) -> dict:
        """
        Identify dominant frequency components via a pure-Python DFT.

        Useful for detecting periodic sensor anomalies (vibration, cycling HVAC, etc.)
        without numpy. O(n²) — keep *values* under ~256 samples for real-time use.
        """
        n = len(values)
        if n < 8:
            return {"peaks": [], "dominant_freq": 0, "periodic": False}

        freqs = []
        for k in range(n // 2):
            real_sum = 0.0
            imag_sum = 0.0
            for t in range(n):
                angle     = 2 * math.pi * k * t / n
                real_sum += values[t] * math.cos(angle)
                imag_sum -= values[t] * math.sin(angle)
            magnitude = math.sqrt(real_sum ** 2 + imag_sum ** 2) / n
            freqs.append({"freq": k, "magnitude": round(magnitude, 4)})

        freqs.sort(key=lambda x: x["magnitude"], reverse=True)
        return {
            "dominant_freq": freqs[0]["freq"]      if freqs else 0,
            "top_3":         freqs[:3],
            "periodic":      freqs[0]["magnitude"] > 0.3 if freqs else False,
        }
