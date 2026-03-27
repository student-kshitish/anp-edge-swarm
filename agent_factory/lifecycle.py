"""
agent_factory/lifecycle.py — Manages the full lifecycle of spawned agents.
"""

import time
import threading
import logging

logger = logging.getLogger(__name__)


class AgentLifecycle:
    def __init__(self):
        self.active_agents: dict[str, dict] = {}
        self._lock = threading.Lock()

    def spawn(self, agent_id: str, agent_obj) -> None:
        """Start *agent_obj* and register it under *agent_id*."""
        agent_obj.start()
        with self._lock:
            self.active_agents[agent_id] = {
                "agent": agent_obj,
                "started_at": time.time(),
                "status": "running",
            }
        print(f"[LIFECYCLE] Spawned {agent_id}", flush=True)

    def destroy(self, agent_id: str) -> None:
        """Stop the agent and remove it from the registry."""
        with self._lock:
            entry = self.active_agents.pop(agent_id, None)
        if entry is None:
            return
        entry["agent"]._running = False
        print(f"[LIFECYCLE] Destroyed {agent_id}", flush=True)

    def destroy_all(self) -> None:
        """Destroy every currently active agent."""
        for agent_id in list(self.active_agents.keys()):
            self.destroy(agent_id)

    def status(self) -> dict:
        """Return {agent_id: 'running'} for all active agents."""
        with self._lock:
            return {aid: info["status"] for aid, info in self.active_agents.items()}

    def auto_destroy_after(self, agent_id: str, seconds: float) -> None:
        """Spawn a daemon thread that destroys *agent_id* after *seconds*."""
        def _timer():
            print(f"[LIFECYCLE] Auto-destroying {agent_id} after {seconds}s", flush=True)
            time.sleep(seconds)
            self.destroy(agent_id)

        threading.Thread(target=_timer, daemon=True,
                         name=f"autodestroy-{agent_id}").start()
