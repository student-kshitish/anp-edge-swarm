"""
core/auto_trigger.py — Watches for new peers and spawns appropriate
agents automatically. The brain of autonomous operation.
"""

import threading
import time
from agent_factory.factory import AgentFactory
from core.agent_registry import get_agent_for

TRIGGER_INTERVAL = 5   # seconds between peer checks
MIN_READINGS     = 3   # minimum readings before triggering ML


class AutoTrigger:

    def __init__(self, get_peers_fn, run_pipeline_fn):
        self.get_peers     = get_peers_fn
        self.run_pipeline  = run_pipeline_fn
        self.factory       = AgentFactory()
        self.known_peers   = {}
        self.running       = False
        self.active_agents = {}
        self._lock         = threading.Lock()

    def start(self):
        self.running = True
        threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="auto-trigger",
        ).start()
        print("[AUTO] Autonomous mode started")
        print("[AUTO] Waiting for devices to join swarm...")

    def stop(self):
        self.running = False

    def _watch_loop(self):
        while self.running:
            try:
                peers = self.get_peers()

                for peer_id, peer_info in peers.items():
                    if peer_id not in self.known_peers:
                        self.known_peers[peer_id] = peer_info
                        print(f"[AUTO] New device joined: {peer_id[:12]}")
                        self._on_device_join(peer_id, peer_info)

                # Check for devices that left
                for peer_id in list(self.known_peers.keys()):
                    if peer_id not in peers:
                        print(f"[AUTO] Device left: {peer_id[:12]}")
                        self._on_device_leave(peer_id)
                        del self.known_peers[peer_id]

            except Exception as e:
                print(f"[AUTO] Watch error: {e}")

            time.sleep(TRIGGER_INTERVAL)

    def _on_device_join(self, peer_id: str, peer_info: dict):
        # peer_info format from peer_server: {node_id, caps, addr, roles, last_seen}
        # caps format: {ram_gb, cpu_cores, roles, os}
        caps      = peer_info.get("caps", peer_info)
        roles     = caps.get("roles", peer_info.get("roles", ["worker"]))
        modalities = caps.get("modalities", ["text"])

        print(f"[AUTO] Device capabilities: roles={roles} modalities={modalities}")

        spawned = []

        if "sensor" in roles or "worker" in roles:
            for sensor_type in ["attendance", "temperature", "materials"]:
                agents = self.factory.create_from_intent({
                    "goal":         f"monitor {sensor_type}",
                    "data_required": [sensor_type],
                    "priority":      "normal",
                })
                spawned.extend(agents)

        if "image" in modalities or "vision" in roles:
            print(f"[AUTO] Vision-capable device — spawning vision monitor")

        if "audio" in modalities:
            print(f"[AUTO] Audio-capable device — spawning audio monitor")

        print(f"[AUTO] Spawned {len(spawned)} agents for {peer_id[:12]}")

    def _on_device_leave(self, peer_id: str):
        print(f"[AUTO] Cleaning up agents for {peer_id[:12]}")
