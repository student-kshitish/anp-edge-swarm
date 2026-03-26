"""
bus/message_bus.py — In-process A2A message bus.
Agents subscribe to their own agent_id; others publish to that id.
"""

import queue
import threading
import time
from typing import Any

_lock = threading.Lock()


class MessageBus:
    def __init__(self):
        self._queues: dict[str, queue.Queue] = {}
        self._log: list[dict] = []

    def subscribe(self, agent_id: str) -> None:
        """Register an agent_id so it can receive messages."""
        with _lock:
            if agent_id not in self._queues:
                self._queues[agent_id] = queue.Queue()

    def publish(self, to: str, message: Any, sender: str = "anonymous") -> bool:
        """Send a message to agent_id. Returns False if recipient unknown."""
        with _lock:
            q = self._queues.get(to)
            if q is None:
                return False
            entry = {
                "from": sender,
                "to": to,
                "message": message,
                "ts": time.time(),
            }
            q.put(entry)
            self._log.append(entry)
            return True

    def receive(self, agent_id: str, timeout: float = 1.0) -> dict | None:
        """Block up to *timeout* seconds waiting for a message. Returns None on timeout."""
        with _lock:
            q = self._queues.get(agent_id)
        if q is None:
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_log(self) -> list[dict]:
        """Return a copy of all messages ever published on this bus."""
        with _lock:
            return list(self._log)


# Shared singleton
bus = MessageBus()
