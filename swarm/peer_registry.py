"""
swarm/peer_registry.py — Local registry of discovered swarm peers.

Maintains capability info, IP address, and last-seen timestamp for
each peer.  Stale peers (silent > `timeout` seconds) are evicted.

Integrates with dht_discovery: when a peer is registered here it is
also added to dht_discovery.known_peers so task_distributor can use it.
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)


class PeerRegistry:
    def __init__(self):
        self.peers: dict = {}
        self._lock = threading.Lock()

    def register(self, node_id: str, caps: dict, addr: str) -> None:
        """Add or refresh a peer entry."""
        with self._lock:
            self.peers[node_id] = {
                "caps":      caps,
                "addr":      addr,
                "roles":     caps.get("roles", ["worker"]),
                "last_seen": time.time(),
            }
            print(f"[REGISTRY] Peer registered: {node_id} @ {addr}", flush=True)

        # Mirror into dht_discovery.known_peers so task_distributor can see it
        try:
            from swarm.dht_discovery import register_peer
            register_peer(node_id, self.peers[node_id])
        except Exception:
            pass

    def get_all(self) -> dict:
        """Return a snapshot of all known peers."""
        with self._lock:
            return dict(self.peers)

    def get_workers(self) -> list:
        """Return peer-info dicts for nodes with the 'worker' role."""
        with self._lock:
            return [
                v for v in self.peers.values()
                if "worker" in v.get("roles", [])
            ]

    def evict_stale(self, timeout: float = 60.0) -> None:
        """Remove peers not seen within *timeout* seconds."""
        now = time.time()
        with self._lock:
            stale = [
                k for k, v in self.peers.items()
                if now - v["last_seen"] > timeout
            ]
            for k in stale:
                del self.peers[k]
                print(f"[REGISTRY] Evicted stale peer: {k}", flush=True)


# Module-level singleton
registry = PeerRegistry()
