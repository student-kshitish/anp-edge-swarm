"""
swarm/discovery.py — UDP broadcast peer discovery.
Broadcasts this node's capabilities to the LAN and collects responses.

Broadcasts to two addresses every cycle:
  - 255.255.255.255  (limited broadcast, works Linux → Windows)
  - 192.168.1.255    (subnet broadcast, works across some routers)
"""

import socket
import json
import threading
import time
import logging
from swarm.capability import get_capabilities

logger = logging.getLogger(__name__)

BROADCAST_PORT = 50000
SUBNET_BROADCAST = "192.168.1.255"
BROADCAST_INTERVAL = 5       # seconds between announcements
PEER_TIMEOUT = 15            # seconds before a silent peer is dropped

_known_nodes: dict[str, dict] = {}   # node_id -> {caps, last_seen}
_lock = threading.Lock()
_running = False


def add_known_peer(ip: str) -> None:
    """Manually register a peer by IP (useful as a static fallback)."""
    with _lock:
        # Use IP as a temporary key until a real announce arrives
        existing_ids = [v["addr"] for v in _known_nodes.values()]
        if ip not in existing_ids:
            logger.info("Manual peer added: %s", ip)
            # We don't have caps yet; they'll be filled in on first announce
            _known_nodes.setdefault(f"static:{ip}", {
                "caps": {},
                "addr": ip,
                "last_seen": time.time(),
            })


def _broadcast_loop():
    """Periodically broadcast this node's capabilities to both broadcast addresses
    and directly to any already-known peer IPs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    caps = get_capabilities()
    payload = json.dumps({"type": "announce", "caps": caps}).encode()

    while _running:
        print(f"[DISCOVERY] Broadcasting capability: node_id={caps['node_id']}")
        broadcast_targets = ["255.255.255.255", SUBNET_BROADCAST]
        # Also unicast directly to every peer we already know
        with _lock:
            peer_ips = [v["addr"] for v in _known_nodes.values()]
        for ip in peer_ips:
            if ip not in broadcast_targets:
                broadcast_targets.append(ip)

        for dest in broadcast_targets:
            try:
                sock.sendto(payload, (dest, BROADCAST_PORT))
                logger.debug("Broadcast sent to %s: %s", dest, caps["node_id"])
            except OSError as e:
                logger.warning("Broadcast error (%s): %s", dest, e)
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
            print(f"[DISCOVERY] Raw packet from {addr}: {data[:80]}")
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
                    print(f"[DISCOVERY] Added peer: {peer_id} @ {addr[0]}")
                elif peer_id == my_id:
                    pass  # own broadcast reflected back, ignore silently
                else:
                    print(f"[DISCOVERY] Packet missing node_id, raw caps: {caps}")
        except socket.timeout:
            pass
        except json.JSONDecodeError as e:
            print(f"[DISCOVERY] JSON parse error from {addr}: {e} | raw: {data[:80]}")
            logger.debug("Bad packet (JSON): %s", e)
        except KeyError as e:
            print(f"[DISCOVERY] KeyError parsing packet from {addr}: {e} | raw: {data[:80]}")
            logger.debug("Bad packet (KeyError): %s", e)
        except Exception as e:
            print(f"[DISCOVERY] Unexpected error from {addr}: {type(e).__name__}: {e}")
            logger.warning("Unexpected listen error: %s", e)

        # Evict stale peers
        now = time.time()
        with _lock:
            stale = [k for k, v in _known_nodes.items()
                     if now - v["last_seen"] > PEER_TIMEOUT]
            for k in stale:
                logger.info("Peer timed out: %s", k)
                del _known_nodes[k]

    sock.close()


def start(bootstrap_ip=None, use_bluetooth=False):
    """Start UDP discovery (non-blocking).

    Args:
        bootstrap_ip:   Unused here (kept for API compatibility with dht_discovery).
        use_bluetooth:  When True, also start Bluetooth mesh transport as an
                        additional peer-discovery channel.  Falls back silently
                        if bleak is not installed or BLE is unavailable.
    """
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_broadcast_loop, daemon=True, name="disc-broadcast").start()
    threading.Thread(target=_listen_loop,    daemon=True, name="disc-listen").start()
    logger.info("Discovery started on UDP port %d", BROADCAST_PORT)

    if use_bluetooth:
        try:
            from swarm.bluetooth_discovery import start as bt_start

            def on_bt_discover(node):
                node_id = node["caps"].get("node_id", "?")
                print(f"[DISC] BT peer: {node_id[:12]}")

            bt_start(on_discover=on_bt_discover)
            print("[DISC] Bluetooth transport active")
        except ImportError:
            print("[DISC] bleak not installed — WiFi only")
        except Exception as e:
            print(f"[DISC] BT failed: {e} — WiFi only")


def stop():
    """Stop UDP discovery."""
    global _running
    _running = False


def get_known_nodes() -> dict:
    """Return a copy (not a reference) of currently known peer nodes.
    Safe to call from any thread — prevents race conditions."""
    with _lock:
        return {k: dict(v) for k, v in _known_nodes.items()}


if __name__ == "__main__":
    import time
    start()
    print("Running discovery for 30 seconds...")
    for i in range(30):
        time.sleep(1)
        print(f"t+{i+1}s known_nodes: {list(get_known_nodes().keys())}")
