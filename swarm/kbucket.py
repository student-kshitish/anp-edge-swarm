"""
swarm/kbucket.py — K-bucket routing table with XOR metric.

Constants:
    K     = 20   (max nodes per bucket)
    ALPHA = 3    (parallelism factor for lookups)

Classes:
    KBucket      — one bucket covering a prefix range
    RoutingTable — 160 buckets indexed by XOR distance bit length
"""

import time

K = 20
ALPHA = 3


def _xor_distance(id1: str, id2: str) -> int:
    """XOR distance between two 40-char hex node IDs."""
    return int(id1, 16) ^ int(id2, 16)


class KBucket:
    """
    A single k-bucket covering IDs whose XOR distance falls in
    [range_min, range_max).

    nodes: list of (node_id, ip, port, last_seen) — oldest at head,
           newest at tail (LRU order).
    """

    def __init__(self, range_min: int, range_max: int):
        self.range_min = range_min
        self.range_max = range_max
        self.nodes: list = []   # (node_id, ip, port, last_seen)

    def add(self, node_id: str, ip: str, port: int) -> None:
        """Add or refresh a node. Evict head if bucket is full."""
        for i, (nid, _, _, _) in enumerate(self.nodes):
            if nid == node_id:
                # Refresh: move to tail with updated last_seen
                self.nodes.pop(i)
                self.nodes.append((node_id, ip, port, time.time()))
                return

        if len(self.nodes) < K:
            self.nodes.append((node_id, ip, port, time.time()))
        else:
            # Evict oldest (head), add newest (tail)
            self.nodes.pop(0)
            self.nodes.append((node_id, ip, port, time.time()))

    def get_closest(self, target_id: str, count: int) -> list:
        """Return up to `count` nodes sorted by XOR distance to target_id."""
        return sorted(
            self.nodes,
            key=lambda n: _xor_distance(n[0], target_id)
        )[:count]

    def evict_stale(self, max_age: float) -> None:
        """Remove nodes not seen within max_age seconds."""
        now = time.time()
        self.nodes = [n for n in self.nodes if now - n[3] <= max_age]


class RoutingTable:
    """
    160-bucket Kademlia routing table.

    Each bucket i covers nodes whose XOR distance to own_id has
    its highest set bit at position i (i.e. distance in [2^i, 2^(i+1))).
    Bucket 0 is used for exact matches (distance == 0, should never
    happen in practice since we skip own_id).
    """

    def __init__(self, own_id: str):
        self.own_id = own_id
        self.buckets = [KBucket(i, i + 1) for i in range(160)]

    def _bucket_index(self, node_id: str) -> int:
        dist = _xor_distance(self.own_id, node_id)
        if dist == 0:
            return 0
        return dist.bit_length() - 1   # 0-based bit position of highest set bit

    def add_node(self, node_id: str, ip: str, port: int) -> None:
        """Insert or refresh a node. Own ID is silently ignored."""
        if node_id == self.own_id:
            return
        idx = self._bucket_index(node_id)
        self.buckets[idx].add(node_id, ip, port)

    def find_closest(self, target_id: str, count: int = K) -> list:
        """Return up to `count` nodes closest to target_id by XOR distance."""
        all_nodes: list = []
        for bucket in self.buckets:
            all_nodes.extend(bucket.nodes)
        return sorted(
            all_nodes,
            key=lambda n: _xor_distance(n[0], target_id)
        )[:count]

    def all_nodes(self) -> list:
        """Return a flat list of all known (node_id, ip, port, last_seen) tuples."""
        result: list = []
        for bucket in self.buckets:
            result.extend(bucket.nodes)
        return result

    def evict_stale(self, max_age: float) -> None:
        """Remove nodes not seen within max_age seconds from all buckets."""
        for bucket in self.buckets:
            bucket.evict_stale(max_age)

    def size(self) -> int:
        """Total number of nodes across all buckets."""
        return sum(len(b.nodes) for b in self.buckets)
