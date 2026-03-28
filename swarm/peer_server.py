# Windows admin: netsh advfirewall firewall add rule name="EdgeMind Peer" protocol=TCP dir=in localport=50010 action=allow

"""
swarm/peer_server.py — Pull-based TCP capability server.

Fixes the Windows → Linux UDP discovery failure by flipping to a
pull model: any node can connect on TCP 50010 to exchange capabilities.

Protocol (one TCP connection per exchange):
  1. Server sends own capability JSON
  2. Server shuts down its write side (signals EOF to reader)
  3. Client sends its capability JSON and closes
  4. Server reads client caps and registers the peer

Usage:
    from swarm.peer_server import start_server, get_known_nodes
    start_server()
"""

import json
import socket
import threading
import time
import logging

from swarm.capability import get_capabilities

logger = logging.getLogger(__name__)

PEER_PORT = 50010

_known_nodes: dict = {}   # node_id -> {caps, addr, roles, last_seen}
_lock = threading.Lock()
_started = False


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _add_peer(node_id: str, caps: dict, addr: str) -> None:
    entry = {
        "caps":      caps,
        "addr":      addr,
        "roles":     caps.get("roles", ["worker"]),
        "last_seen": time.time(),
    }
    with _lock:
        _known_nodes[node_id] = entry
    # Mirror into dht_discovery.known_peers so task_distributor can see it
    try:
        from swarm.dht_discovery import register_peer
        register_peer(node_id, entry)
    except Exception:
        pass


def _handle_client(conn: socket.socket, addr: tuple) -> None:
    try:
        my_caps = get_capabilities()

        # Step 1: send our caps, then signal EOF so the client can read cleanly
        conn.sendall(json.dumps(my_caps).encode())
        conn.shutdown(socket.SHUT_WR)

        # Step 2: read client caps (they send after reading ours)
        conn.settimeout(5.0)
        chunks = []
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)

        data = b"".join(chunks)
        if data:
            their_caps = json.loads(data.decode())
            node_id = their_caps.get("node_id")
            if node_id:
                _add_peer(node_id, their_caps, addr[0])
                print(f"[PEER] Connected to {node_id} at {addr[0]}", flush=True)
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("[PEER] Client handler error from %s: %s", addr[0], e)
    finally:
        conn.close()


def _server_loop() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", PEER_PORT))
    server.listen(10)
    server.settimeout(2.0)
    logger.info("[PEER] Server listening on TCP port %d", PEER_PORT)

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(
                target=_handle_client,
                args=(conn, addr),
                daemon=True,
                name=f"peer-conn-{addr[0]}",
            ).start()
        except socket.timeout:
            pass
        except OSError as e:
            logger.debug("[PEER] Server accept error: %s", e)


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def start_server() -> None:
    """Start the peer capability server (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_server_loop, daemon=True, name="peer-server").start()
    print(f"[PEER] Capability server started on TCP port {PEER_PORT}", flush=True)


def get_known_nodes() -> dict:
    """Return a snapshot of peers discovered via TCP exchange."""
    with _lock:
        return dict(_known_nodes)
