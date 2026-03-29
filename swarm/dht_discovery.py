"""
swarm/dht_discovery.py — Thin wrapper over KademliaNode.

Matches the old discovery.py API so callers need no changes:
    from swarm.dht_discovery import start, get_known_nodes, find_peer, register_peer, stop

The module holds a single KademliaNode singleton (_node).
All functions delegate to it.
"""

from swarm.kademlia_node import KademliaNode

_node = KademliaNode()


def start(bootstrap_ip: str = None, bootstrap_port: int = 6881) -> None:
    """
    Start the Kademlia DHT node.

    Args:
        bootstrap_ip:   IP of a known node to bootstrap from.
                        If None, node starts in isolation (useful for the
                        first bootstrap server or LAN-only deployments).
        bootstrap_port: UDP port of the bootstrap node (default 6881).
    """
    _node.start(bootstrap_ip, bootstrap_port)


def get_known_nodes() -> dict:
    """
    Return all peers discovered via ANNOUNCE / PONG messages.

    Format: {node_id: cap_dict}
    where cap_dict contains: node_id, os, cpu_cores, ram_gb, roles, addr, ...
    """
    return _node.get_all_peers()


def find_peer(node_id: str) -> dict:
    """
    Look up a specific peer by node_id in the DHT (blocking, ~2 s).

    Returns the peer's capability dict, or {} if not found.
    """
    return _node.find_peer(node_id)


def register_peer(node_id: str, cap: dict, addr: str = "") -> None:
    """
    Manually inject a peer into the known_peers dict.

    Used by peer_server / peer_client after a TCP capability exchange.
    """
    if addr:
        cap = dict(cap)
        cap.setdefault("addr", addr)
    _node.known_peers[node_id] = cap


def stop() -> None:
    """Shut down the Kademlia node."""
    _node.stop()
