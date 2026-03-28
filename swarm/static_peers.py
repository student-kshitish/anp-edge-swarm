"""
swarm/static_peers.py — Hardcoded fallback peers for environments where
UDP broadcast is partially blocked (e.g. Windows router blocking 255.255.255.255).

register_static_peers() directly unicasts our capability packet to each known IP
so they can discover us even without receiving our broadcast.
"""

import socket
import json

STATIC_PEERS = [
    "192.168.1.9",    # Windows laptop
    "192.168.1.40",   # Victus Linux
]


def register_static_peers():
    """Unicast our capability announcement to every known static peer IP."""
    from swarm.discovery import BROADCAST_PORT, add_known_peer
    from swarm.capability import get_capabilities

    caps = get_capabilities()
    payload = json.dumps({"type": "announce", "caps": caps}).encode()
    my_ip = None

    # Best-effort: detect our own IP so we skip self-sends
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    for ip in STATIC_PEERS:
        if ip == my_ip:
            continue
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            sock.sendto(payload, (ip, BROADCAST_PORT))
            sock.close()
            add_known_peer(ip)
            print(f"[STATIC] Sent capability to {ip}")
        except Exception as e:
            print(f"[STATIC] Could not reach {ip}: {e}")
