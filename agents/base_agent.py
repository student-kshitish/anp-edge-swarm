"""
agents/base_agent.py — BaseAgent that every swarm agent inherits from.
"""

import threading
import logging
from bus.message_bus import bus

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, agent_id: str, role: str):
        self.agent_id = agent_id
        self.role = role
        self._thread: threading.Thread | None = None
        self._running = False
        bus.subscribe(agent_id)
        logger.info("[%s] subscribed to bus (role=%s)", agent_id, role)

    # ------------------------------------------------------------------ #
    # Messaging
    # ------------------------------------------------------------------ #

    def send(self, to: str, message: dict) -> bool:
        """Publish a message to another agent."""
        ok = bus.publish(to=to, message=message, sender=self.agent_id)
        if not ok:
            logger.warning("[%s] could not deliver to '%s' (not subscribed)", self.agent_id, to)
        return ok

    def receive(self, timeout: float = 1.0) -> dict | None:
        """Wait up to *timeout* seconds for an incoming message."""
        return bus.receive(self.agent_id, timeout=timeout)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def run(self):
        """Override in subclasses — called in a daemon thread by start()."""
        raise NotImplementedError

    def start(self):
        """Launch run() in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._safe_run,
            name=self.agent_id,
            daemon=True,
        )
        self._thread.start()
        logger.info("[%s] started", self.agent_id)

    def stop(self):
        self._running = False

    def _safe_run(self):
        try:
            self.run()
        except Exception as e:
            logger.exception("[%s] crashed: %s", self.agent_id, e)
