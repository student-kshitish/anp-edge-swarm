"""
ml/context_manager.py — Prevents context rot in long-running swarms.

Agents operate on isolated subtasks and can lose sight of the system's
overarching goal. ContextManager maintains a rolling window of the last
MAX_CONTEXT events alongside the global goal so that every LLM call
begins with coherent, up-to-date context rather than a blank slate.
"""

import json
import threading
import time


class ContextManager:
    """Thread-safe rolling context window for the ML pipeline."""

    def __init__(self, max_context: int = 50):
        self.global_goal    = ""
        self.local_tasks    = {}       # task_id → task record
        self.context_window = []       # ordered list of recent events
        self.max_context    = max_context
        self._lock          = threading.Lock()
        self.created_at     = time.time()

    # ------------------------------------------------------------------
    # Goal management
    # ------------------------------------------------------------------

    def set_global_goal(self, goal: str):
        with self._lock:
            self.global_goal = goal
            self._add_context("GOAL_SET", {"goal": goal})
        print(f"[CONTEXT] Global goal set: {goal}")

    # ------------------------------------------------------------------
    # Task tracking
    # ------------------------------------------------------------------

    def add_local_task(self, task_id: str, task_type: str, node_id: str):
        with self._lock:
            self.local_tasks[task_id] = {
                "type":       task_type,
                "node":       node_id,
                "status":     "active",
                "started_at": time.time(),
            }
            self._add_context("TASK_START", {
                "task_type": task_type,
                "node":      node_id[:12],
            })

    def complete_task(self, task_id: str, result: dict):
        with self._lock:
            if task_id in self.local_tasks:
                self.local_tasks[task_id]["status"]       = "complete"
                self.local_tasks[task_id]["result"]       = result
                self.local_tasks[task_id]["completed_at"] = time.time()
            self._add_context("TASK_COMPLETE", {
                "task_id": task_id[:8],
                "status":  result.get("status", "OK"),
            })

    # ------------------------------------------------------------------
    # Context summaries
    # ------------------------------------------------------------------

    def get_context_summary(self) -> str:
        with self._lock:
            active   = sum(
                1 for t in self.local_tasks.values() if t["status"] == "active"
            )
            complete = sum(
                1 for t in self.local_tasks.values() if t["status"] == "complete"
            )
            uptime = int(time.time() - self.created_at)
            return (
                f"Global goal: {self.global_goal}\n"
                f"Active tasks: {active}, Complete: {complete}\n"
                f"Uptime: {uptime}s\n"
                f"Recent events: {len(self.context_window)}"
            )

    def build_llm_context(self) -> str:
        """
        Build a compact context string to prepend to every LLM prompt.

        Keeps the last 10 events so the model understands recent activity
        without blowing the context window on history.
        """
        with self._lock:
            active_count = sum(
                1 for t in self.local_tasks.values() if t["status"] == "active"
            )
            ctx  = "SYSTEM CONTEXT:\n"
            ctx += f"Goal: {self.global_goal}\n"
            ctx += f"Active tasks: {active_count}\n"

            recent = self.context_window[-10:]
            if recent:
                ctx += "Recent events:\n"
                for e in recent:
                    ctx += f"  [{e['type']}] {json.dumps(e['data'])}\n"
            return ctx

    def get_status(self) -> dict:
        with self._lock:
            return {
                "global_goal":    self.global_goal,
                "active_tasks":   sum(
                    1 for t in self.local_tasks.values()
                    if t["status"] == "active"
                ),
                "complete_tasks": sum(
                    1 for t in self.local_tasks.values()
                    if t["status"] == "complete"
                ),
                "context_size":   len(self.context_window),
                "uptime":         int(time.time() - self.created_at),
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _add_context(self, event_type: str, data: dict):
        """Append an event and enforce the rolling window limit."""
        self.context_window.append({
            "type":      event_type,
            "data":      data,
            "timestamp": time.time(),
        })
        if len(self.context_window) > self.max_context:
            self.context_window = self.context_window[-self.max_context:]
