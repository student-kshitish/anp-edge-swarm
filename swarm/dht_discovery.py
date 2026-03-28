"""
swarm/dht_discovery.py — Kademlia DHT peer-to-peer discovery.

Works across different networks and locations (not LAN-only).

Each node:
  1. Joins the DHT by bootstrapping from a known node (or public BitTorrent nodes)
  2. Stores its own capability info under its node_id key
  3. Re-announces every 30 seconds so the entry stays fresh

Usage:
    from swarm.dht_discovery import start, get_known_nodes
    start(bootstrap_ip="1.2.3.4")   # or start() for public bootstrap
"""

import asyncio
import json
import socket
import threading
import logging

logger = logging.getLogger(__name__)

BOOTSTRAP_NODES = [
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
]

_loop: asyncio.AbstractEventLoop | None = None


class DHTNode:
    def __init__(self):
        self.node_id = None
        self.server = None
        self.known_peers: dict = {}
        self.port = 6881

    async def start(self, bootstrap_ip=None, bootstrap_port=6881):
        from kademlia.network import Server
        self.server = Server()
        await self.server.listen(self.port)

        if bootstrap_ip:
            await self.server.bootstrap([(bootstrap_ip, bootstrap_port)])
        else:
            await self.server.bootstrap(BOOTSTRAP_NODES)

        from swarm.capability import get_capabilities
        cap = get_capabilities()
        self.node_id = cap["node_id"]
        await self.server.set(cap["node_id"], json.dumps(cap))
        print(f"[DHT] Node registered: {cap['node_id']}", flush=True)

        # Start periodic re-announce
        asyncio.ensure_future(self._announce_loop())

    async def _announce_loop(self):
        """Re-announce our capability in the DHT every 30 seconds."""
        while True:
            await asyncio.sleep(30)
            await self.announce()

    async def announce(self):
        """Store our current capability info in the DHT."""
        if not self.server:
            return
        from swarm.capability import get_capabilities
        cap = get_capabilities()
        await self.server.set(cap["node_id"], json.dumps(cap))

    async def find_peer(self, node_id: str) -> dict:
        """Look up a peer by node_id. Returns parsed capability dict or {}."""
        if not self.server:
            return {}
        result = await self.server.get(node_id)
        if result:
            return json.loads(result)
        return {}

    def register_peer(self, node_id: str, info: dict) -> None:
        """Add or update a peer in the local known_peers dict."""
        self.known_peers[node_id] = info

    def stop(self):
        if self.server:
            self.server.stop()


# ------------------------------------------------------------------ #
# Module-level singleton + wrapper functions (match old discovery API)
# ------------------------------------------------------------------ #

_dht = DHTNode()


def start(bootstrap_ip=None):
    """
    Start the Kademlia DHT node in a background event loop.

    Args:
        bootstrap_ip: IP of a known bootstrap node.
                      If None, uses public BitTorrent DHT bootstrap nodes.
    """
    global _loop
    _loop = asyncio.new_event_loop()
    threading.Thread(
        target=_loop.run_forever, daemon=True, name="dht-loop"
    ).start()
    fut = asyncio.run_coroutine_threadsafe(_dht.start(bootstrap_ip), _loop)
    logger.info("[DHT] Kademlia DHT node starting (bootstrap_ip=%s)...", bootstrap_ip or "public")
    return fut


def get_known_nodes() -> dict:
    """Return the local dict of discovered peers {node_id: peer_info}."""
    return _dht.known_peers


def find_peer(node_id: str) -> dict:
    """
    Look up a peer by node_id in the DHT (blocking, ≤5 s).

    Returns the peer's capability dict, or {} if not found.
    """
    if _loop is None:
        return {}
    fut = asyncio.run_coroutine_threadsafe(_dht.find_peer(node_id), _loop)
    try:
        return fut.result(timeout=5.0)
    except Exception as e:
        logger.debug("[DHT] find_peer error: %s", e)
        return {}


def register_peer(node_id: str, info: dict) -> None:
    """Manually add a peer to the known_peers dict (used by peer_registry)."""
    _dht.register_peer(node_id, info)


def stop():
    _dht.stop()
    if _loop:
        _loop.call_soon_threadsafe(_loop.stop)
