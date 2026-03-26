"""
swarm/discovery.py — UDP broadcast peer discovery.
Broadcasts this node's capabilities to the LAN and collects responses.
"""

import socket
import json
import threading
import time
import logging
from swarm.capability import get_capabilities

logger = logging.getLogger(__name__)

BROADCAST_PORT = 50001
BROADCAST_INTERVAL = 5       # seconds between announcements
PEER_TIMEOUT = 15            # seconds before a silent peer is dropped

_known_nodes: dict[str, dict] = {}   # node_id -> {caps, last_seen}
_lock = threading.Lock()
_running = False


def _broadcast_loop():
    """Periodically broadcast this node's capabilities."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    caps = get_capabilities()
    payload = json.dumps({"type": "announce", "caps": caps}).encode()

    while _running:
        try:
            sock.sendto(payload, ("<broadcast>", BROADCAST_PORT))
            logger.debug("Broadcast sent: %s", caps["node_id"])
        except OSError as e:
            logger.warning("Broadcast error: %s", e)
        time.sleep(BROADCAST_INTERVAL)

    sock.close()


def _listen_loop():
    """Listen for announcements from other nodes."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", BROADCAST_PORT))
    sock.settimeout(2.0)

    my_id = get_capabilities()["node_id"]

    while _running:
        try:
            data, addr = sock.recvfrom(4096)
            msg = json.loads(data.decode())
            if msg.get("type") == "announce":
                caps = msg["caps"]
                peer_id = caps.get("node_id")
                if peer_id and peer_id != my_id:
                    with _lock:
                        _known_nodes[peer_id] = {
                            "caps": caps,
                            "addr": addr[0],
                            "last_seen": time.time(),
                        }
                    logger.info("Discovered peer: %s @ %s", peer_id, addr[0])
        except socket.timeout:
            pass
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("Bad packet: %s", e)

        # Evict stale peers
        now = time.time()
        with _lock:
            stale = [k for k, v in _known_nodes.items()
                     if now - v["last_seen"] > PEER_TIMEOUT]
            for k in stale:
                logger.info("Peer timed out: %s", k)
                del _known_nodes[k]

    sock.close()


def start():
    """Start UDP discovery (non-blocking)."""
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_broadcast_loop, daemon=True, name="disc-broadcast").start()
    threading.Thread(target=_listen_loop,    daemon=True, name="disc-listen").start()
    logger.info("Discovery started on UDP port %d", BROADCAST_PORT)


def stop():
    """Stop UDP discovery."""
    global _running
    _running = False


def get_known_nodes() -> dict:
    """Return a snapshot of currently known peer nodes."""
    with _lock:
        return {k: dict(v) for k, v in _known_nodes.items()}
