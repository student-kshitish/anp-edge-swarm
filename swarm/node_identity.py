"""
swarm/node_identity.py — Permanent 160-bit node identity.

Derives a stable node ID from MAC address + hostname using SHA-1,
then persists it to .node_identity so the same machine always gets
the same ID across restarts.

Usage:
    from swarm.node_identity import get_node_id
    node_id = get_node_id()   # 40-char hex string (160 bits)
"""

import hashlib
import os
import socket
import uuid

_IDENTITY_FILE = ".node_identity"


def get_node_id() -> str:
    """Return this node's permanent 160-bit ID as a 40-char hex string."""
    if os.path.exists(_IDENTITY_FILE):
        with open(_IDENTITY_FILE, "r") as f:
            nid = f.read().strip()
            if len(nid) == 40:
                return nid

    mac = uuid.getnode()          # 48-bit MAC address integer
    hostname = socket.gethostname()
    raw = f"{mac}:{hostname}".encode("utf-8")
    node_id = hashlib.sha1(raw).hexdigest()   # 40 hex chars = 160 bits

    with open(_IDENTITY_FILE, "w") as f:
        f.write(node_id)

    return node_id
