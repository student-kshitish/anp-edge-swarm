"""
ml/task_types.py — Task constants and shared data schemas.
"""

from dataclasses import dataclass, field
from typing import Optional

TASKS = [
    "clean",
    "anomaly",
    "trend",
    "history",
    "action",
]


@dataclass
class TaskResult:
    task_type: str
    node_id: str
    result: dict
    duration_ms: float
    success: bool
    error: Optional[str] = None
