"""
ml/task_decomposer.py — Splits incoming sensor data into parallel tasks
and assigns each task to the best available node.
"""

import socket
from ml.task_types import TASKS


class TaskDecomposer:
    """Assigns specialised tasks to nodes based on capability scores."""

    # Minimum capability keys expected from node advertisements
    _SCORE_WEIGHTS = {
        "ram_gb":    2.0,
        "cpu_cores": 1.5,
    }
    _ROLE_BONUS = {
        "gpu":       20.0,
        "inference": 15.0,
        "compute":   10.0,
        "storage":   5.0,
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decompose(self, sensor_data: dict, known_nodes: dict) -> dict:
        """
        Return an assignment plan mapping each task to a node.

        known_nodes format:
            {
              node_id: {
                "ip": "...",
                "ram_gb": 8,
                "cpu_cores": 4,
                "roles": ["compute"],
                ...
              }
            }

        Returns:
            {
              "clean":   {"node_id": "...", "local": True/False, "ip": "..."},
              "anomaly": {...},
              ...
            }
        """
        local_id = self._local_node_id()

        # Build a merged dict that always includes the local node
        nodes = dict(known_nodes)
        if local_id not in nodes:
            nodes[local_id] = {"ip": "127.0.0.1", "local": True}

        # Score every node
        scored = sorted(
            nodes.items(),
            key=lambda kv: self._score_node(kv[1]),
            reverse=True,
        )

        plan: dict[str, dict] = {}

        if len(scored) == 1:
            # Single node — all tasks run locally in parallel threads
            only_id, only_caps = scored[0]
            only_ip = only_caps.get("ip", "127.0.0.1")
            is_local = only_id == local_id
            for task in TASKS:
                plan[task] = {"node_id": only_id, "local": is_local, "ip": only_ip}
            return plan

        # Multiple nodes — assign by capability affinity
        # Ranked list: [0] highest overall, [1] second, …
        ranked_ids = [nid for nid, _ in scored]
        ranked_caps = {nid: caps for nid, caps in scored}

        # Find best node by specific metric
        def _best_by(metric):
            return max(scored, key=lambda kv: kv[1].get(metric, 0))[0]

        def _has_role(nid, role):
            return role in ranked_caps[nid].get("roles", [])

        # Action → highest GPU/RAM (look for gpu/inference role, else top scorer)
        action_node = next(
            (nid for nid in ranked_ids if _has_role(nid, "gpu") or _has_role(nid, "inference")),
            ranked_ids[0],
        )
        # Trend → highest RAM
        trend_node = _best_by("ram_gb")
        # Anomaly → highest CPU
        anomaly_node = _best_by("cpu_cores")

        assigned = {action_node, trend_node, anomaly_node}
        remaining_tasks = ["clean", "history"]
        remaining_nodes = [nid for nid in ranked_ids if nid not in assigned] or ranked_ids

        # Round-robin remaining tasks to remaining nodes
        task_to_node = {}
        for i, task in enumerate(remaining_tasks):
            task_to_node[task] = remaining_nodes[i % len(remaining_nodes)]

        assignment = {
            "action":  action_node,
            "trend":   trend_node,
            "anomaly": anomaly_node,
            "clean":   task_to_node["clean"],
            "history": task_to_node["history"],
        }

        for task, nid in assignment.items():
            caps = ranked_caps[nid]
            plan[task] = {
                "node_id": nid,
                "local": nid == local_id,
                "ip": caps.get("ip", "127.0.0.1"),
            }

        return plan

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_node(self, node_caps: dict) -> float:
        """Return a 0-100 capability score for a node."""
        score = 0.0

        ram = node_caps.get("ram_gb", 0)
        score += min(ram * self._SCORE_WEIGHTS["ram_gb"], 30.0)   # max 30

        cpu = node_caps.get("cpu_cores", 0)
        score += min(cpu * self._SCORE_WEIGHTS["cpu_cores"], 30.0)  # max 30

        roles = node_caps.get("roles", [])
        for role in roles:
            score += self._ROLE_BONUS.get(role, 0)

        return min(score, 100.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _local_node_id() -> str:
        try:
            return socket.gethostname()
        except Exception:
            return "local"
