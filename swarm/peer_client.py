"""
swarm/peer_client.py — Pull-based TCP capability client.

Connects to known peer IPs and exchanges capability info.
This is the active side of the peer_server protocol:

  1. Client connects to peer:50010
  2. Client reads peer caps (peer sends first, then shuts write side)
  3. Client sends own caps and closes

Works when UDP broadcast is firewalled (e.g. Windows blocking inbound UDP)
because the connection is *initiated from this node* — outbound TCP is
almost never blocked.

Usage:
    from swarm.peer_client import exchange_with_all
    exchange_with_all(["192.168.1.9", "192.168.1.40"])
"""

import json
import socket
import threading
import time
import logging

from swarm.capability import get_capabilities

logger = logging.getLogger(__name__)

PEER_PORT = 50010


# ------------------------------------------------------------------ #
# Single exchange
# ------------------------------------------------------------------ #

def connect_and_exchange(ip: str, port: int = PEER_PORT) -> dict:
    """
    Connect to *ip:port*, exchange capabilities, and return the peer's
    capability dict.  Returns {} on any connection failure.

    Side effects: registers the discovered peer in peer_server._known_nodes
    and dht_discovery.known_peers so task_distributor can route work to it.
    """
    my_caps = get_capabilities()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((ip, port))

        # Step 1: read peer caps (peer sends first, then shuts write side → EOF)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)

        data = b"".join(chunks)
        if not data:
            sock.close()
            return {}

        their_caps = json.loads(data.decode())

        # Step 2: send our caps, then close
        sock.sendall(json.dumps(my_caps).encode())
        sock.close()

        node_id = their_caps.get("node_id")
        if node_id:
            _register(node_id, their_caps, ip)
            print(f"[PEER] Connected to {node_id} at {ip}", flush=True)

        return their_caps

    except (OSError, json.JSONDecodeError) as e:
        logger.debug("[PEER] connect_and_exchange(%s) failed: %s", ip, e)
        return {}


# ------------------------------------------------------------------ #
# Background exchange with retry
# ------------------------------------------------------------------ #

def exchange_with_all(peer_ips: list) -> None:
    """
    Try to exchange capabilities with every IP in *peer_ips*.

    Skips own IP automatically.  Retries unreachable peers every 10 seconds
    until all have responded.  Runs in a daemon thread — returns immediately.
    """
    own_ip = _get_own_ip()
    targets = [ip for ip in peer_ips if ip != own_ip]

    threading.Thread(
        target=_exchange_loop,
        args=(targets,),
        daemon=True,
        name="peer-exchanger",
    ).start()


def _exchange_loop(targets: list) -> None:
    remaining = list(targets)
    while remaining:
        still_pending = []
        for ip in remaining:
            result = connect_and_exchange(ip)
            if not result:
                still_pending.append(ip)
        remaining = still_pending
        if remaining:
            logger.debug("[PEER] Retrying %d unreachable peer(s) in 10 s", len(remaining))
            time.sleep(10)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _register(node_id: str, caps: dict, addr: str) -> None:
    """Update peer_server and dht_discovery with the newly found peer."""
    try:
        from swarm.peer_server import _add_peer
        _add_peer(node_id, caps, addr)
    except Exception as e:
        logger.debug("[PEER] _register error: %s", e)


def _get_own_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
