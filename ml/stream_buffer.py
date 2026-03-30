"""
ml/stream_buffer.py — Sliding window buffer for incoming sensor readings.
"""

import math
from collections import deque
from typing import Optional


class StreamBuffer:
    """Fixed-length sliding window over sensor readings."""

    def __init__(self, maxlen: int = 50):
        self._window: deque = deque(maxlen=maxlen)

    def add(self, reading: dict) -> None:
        self._window.append(reading)

    def is_ready(self) -> bool:
        return len(self._window) >= 10

    def get_window(self) -> list:
        return list(self._window)

    def get_stats(self) -> dict:
        """Return mean/std/min/max per numeric field across the window."""
        window = self.get_window()
        if not window:
            return {}

        # Collect values per field
        fields: dict[str, list] = {}
        for reading in window:
            for key, val in reading.items():
                if isinstance(val, (int, float)):
                    fields.setdefault(key, []).append(float(val))

        stats = {}
        for field_name, values in fields.items():
            n = len(values)
            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
            std = math.sqrt(variance)
            stats[field_name] = {
                "mean": mean,
                "std": std,
                "min": min(values),
                "max": max(values),
                "count": n,
            }
        return stats
