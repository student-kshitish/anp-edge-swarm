"""
swarm/node_identity.py — Permanent 160-bit node identity.

Derives a stable node ID from multiple entropy sources using SHA-1,
then persists it to .node_identity so the same machine always gets
the same ID across restarts.

Usage:
    from swarm.node_identity import get_node_id
    node_id = get_node_id()   # 40-char hex string (160 bits)
"""

import hashlib
import json
import os
import platform
import socket
import time
import uuid

IDENTITY_FILE = ".node_identity"


def get_node_id() -> str:
    """Return this node's permanent 160-bit ID as a 40-char hex string."""
    if os.path.exists(IDENTITY_FILE):
        try:
            with open(IDENTITY_FILE) as f:
                data = json.load(f)
                stored_id = data.get("node_id", "")
                if len(stored_id) == 40:
                    return stored_id
        except Exception:
            pass

    # Generate from multiple entropy sources
    mac      = str(uuid.getnode())
    hostname = platform.node()
    pid      = str(os.getpid())
    ts       = str(time.time())
    random   = str(uuid.uuid4())

    # Try to get real IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"

    raw = f"{mac}-{hostname}-{ip}-{pid}-{ts}-{random}"
    node_id = hashlib.sha1(raw.encode()).hexdigest()

    with open(IDENTITY_FILE, "w") as f:
        json.dump({
            "node_id": node_id,
            "hostname": hostname,
            "ip": ip,
            "created": ts
        }, f, indent=2)

    print(f"[IDENTITY] Generated new node ID: {node_id[:16]}...")
    return node_id
