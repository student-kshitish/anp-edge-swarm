"""
ml/task_decomposer.py — Splits incoming sensor data into parallel tasks
and assigns each task to the best available node.

Handles two peer-registry formats:
  Format A (flat):   {"ip": "...", "ram_gb": 8, "cpu_cores": 4, "roles": [...]}
  Format B (nested): {"caps": {"ram_gb": 8, ...}, "addr": "...", "roles": [...]}
"""

import socket
from ml.task_types import TASKS


class TaskDecomposer:
    """Assigns specialised tasks to nodes based on capability scores."""

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

        Accepts both flat and nested node cap formats — see module docstring.

        Returns:
            {
              "clean":   {"node_id": "...", "local": True/False, "ip": "..."},
              "anomaly": {...},
              ...
            }
        """
        local_id = self._local_node_id()

        # Normalise every node entry and always include local node
        nodes: dict[str, dict] = {}
        for nid, caps in known_nodes.items():
            nodes[nid] = self._normalize_caps(caps)
        if local_id not in nodes:
            nodes[local_id] = {"ram_gb": 0, "cpu_cores": 0, "roles": [],
                                "ip": "127.0.0.1"}

        # Score every node and log
        scored = sorted(
            nodes.items(),
            key=lambda kv: self._score_node(kv[1]),
            reverse=True,
        )
        for nid, ncaps in scored:
            score = self._score_node(ncaps)
            print(f"[DECOMPOSER] Node {nid[:12]:12s} score={score:.1f}")

        plan: dict[str, dict] = {}

        if len(scored) == 1:
            only_id, only_caps = scored[0]
            is_local = only_id == local_id
            for task in TASKS:
                plan[task] = {"node_id": only_id,
                               "local": is_local,
                               "ip": only_caps["ip"]}
                print(f"[DECOMPOSER] {task:8s} -> {only_id[:12]} (local={is_local})")
            return plan

        # Multiple nodes — assign by capability affinity
        ranked_ids  = [nid for nid, _ in scored]
        ranked_caps = {nid: caps for nid, caps in scored}

        def _best_by(metric: str) -> str:
            return max(scored, key=lambda kv: kv[1].get(metric, 0))[0]

        def _has_role(nid: str, role: str) -> bool:
            return role in ranked_caps[nid].get("roles", [])

        # Action → node with GPU/inference role, else top scorer
        action_node = next(
            (nid for nid in ranked_ids
             if _has_role(nid, "gpu") or _has_role(nid, "inference")),
            ranked_ids[0],
        )
        trend_node   = _best_by("ram_gb")
        anomaly_node = _best_by("cpu_cores")

        assigned       = {action_node, trend_node, anomaly_node}
        remaining_nodes = [nid for nid in ranked_ids if nid not in assigned] or ranked_ids

        task_to_node = {}
        for i, task in enumerate(["clean", "history"]):
            task_to_node[task] = remaining_nodes[i % len(remaining_nodes)]

        assignment = {
            "action":  action_node,
            "trend":   trend_node,
            "anomaly": anomaly_node,
            "clean":   task_to_node["clean"],
            "history": task_to_node["history"],
        }

        for task, nid in assignment.items():
            caps    = ranked_caps[nid]
            is_local = nid == local_id
            plan[task] = {"node_id": nid, "local": is_local, "ip": caps["ip"]}
            print(f"[DECOMPOSER] {task:8s} -> {nid[:12]} (local={is_local})")

        return plan

    # ------------------------------------------------------------------
    # Normalisation — FIX 4
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_caps(caps: dict) -> dict:
        """
        Flatten both flat and nested cap formats into a uniform dict.

        Handles:
          caps.get("ram_gb")               (flat format A)
          caps.get("caps", {}).get("ram_gb") (nested format B)
          caps.get("ip") or caps.get("addr") (IP field variants)
        """
        inner = caps.get("caps", {}) if isinstance(caps.get("caps"), dict) else {}
        return {
            "ram_gb":    caps.get("ram_gb")    or inner.get("ram_gb",    0),
            "cpu_cores": caps.get("cpu_cores") or inner.get("cpu_cores", 0),
            "roles":     caps.get("roles")     or inner.get("roles",     []),
            "ip":        caps.get("ip")        or caps.get("addr",       "127.0.0.1"),
        }

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_node(self, node_caps: dict) -> float:
        """Return a 0-100 capability score for a normalised node caps dict."""
        score = 0.0
        score += min(node_caps.get("ram_gb",    0) * self._SCORE_WEIGHTS["ram_gb"],    30.0)
        score += min(node_caps.get("cpu_cores", 0) * self._SCORE_WEIGHTS["cpu_cores"], 30.0)
        for role in node_caps.get("roles", []):
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
