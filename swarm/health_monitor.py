"""
swarm/health_monitor.py — Self-healing network monitor.

Runs a background thread that pings every known peer on a fixed interval.
When a node accumulates MAX_RETRIES consecutive ping failures it is declared
dead and all of its pending tasks are reassigned to surviving peers.
"""

import threading
import time


class HealthMonitor:
    """Monitors peer health and orchestrates task reassignment on node failure."""

    def __init__(self, get_peers_fn, task_distributor):
        self.get_peers     = get_peers_fn
        self.distributor   = task_distributor
        self.node_health   = {}
        self.running       = False

        self.PING_INTERVAL  = 10   # seconds between full sweep
        self.DEAD_THRESHOLD = 30   # seconds of silence → dead
        self.MAX_RETRIES    = 3    # consecutive failures → dead

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self.running = True
        threading.Thread(
            target=self._health_loop,
            daemon=True,
            name="health-monitor",
        ).start()
        print("[HEALTH] Self-healing monitor started")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _health_loop(self):
        while self.running:
            peers = self.get_peers()

            for node_id, info in peers.items():
                ip = info.get("addr") or info.get("ip", "")
                if not ip:
                    continue

                alive = self._ping_node(ip)

                with self._lock:
                    if node_id not in self.node_health:
                        self.node_health[node_id] = {
                            "status":      "alive",
                            "last_seen":   time.time(),
                            "fail_count":  0,
                            "ping_count":  0,
                            "response_ms": 0,
                        }

                    h = self.node_health[node_id]
                    h["ping_count"] += 1

                    if alive["success"]:
                        h["status"]      = "alive"
                        h["last_seen"]   = time.time()
                        h["fail_count"]  = 0
                        h["response_ms"] = alive["ms"]
                    else:
                        h["fail_count"] += 1
                        h["status"]      = "degraded"
                        print(
                            f"[HEALTH] Node {node_id[:12]} "
                            f"ping failed ({h['fail_count']}/{self.MAX_RETRIES})"
                        )

                        if h["fail_count"] >= self.MAX_RETRIES:
                            h["status"] = "dead"
                            print(f"[HEALTH] !! Node {node_id[:12]} declared DEAD")
                            self._on_node_dead(node_id, info)

            # Detect nodes that stopped appearing in the peer list
            now = time.time()
            with self._lock:
                for node_id, h in self.node_health.items():
                    if (
                        now - h["last_seen"] > self.DEAD_THRESHOLD
                        and h["status"] != "dead"
                    ):
                        h["status"] = "dead"
                        print(f"[HEALTH] Node {node_id[:12]} timed out")

            time.sleep(self.PING_INTERVAL)

    # ------------------------------------------------------------------
    # TCP ping (port 50010 — lightweight probe socket)
    # ------------------------------------------------------------------

    def _ping_node(self, ip: str) -> dict:
        import socket
        t0 = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((ip, 50010))
            sock.close()
            ms = int((time.time() - t0) * 1000)
            return {"success": True, "ms": ms}
        except Exception:
            return {"success": False, "ms": 0}

    # ------------------------------------------------------------------
    # Failure handler
    # ------------------------------------------------------------------

    def _on_node_dead(self, node_id: str, info: dict):
        print(f"[HEALTH] Reassigning tasks from dead node {node_id[:12]}")

        pending = self.distributor.get_pending_tasks(node_id)

        if not pending:
            print(f"[HEALTH] No pending tasks for {node_id[:12]}")
            return

        peers = self.get_peers()
        alive_peers = {
            pid: pinfo
            for pid, pinfo in peers.items()
            if self.get_node_status(pid) == "alive" and pid != node_id
        }

        if not alive_peers:
            print("[HEALTH] No alive peers — running tasks locally")
            for task in pending:
                self.distributor.run_locally(task)
            return

        for task in pending:
            print(
                f"[HEALTH] Reassigning task {task['type']} "
                f"from {node_id[:12]}"
            )
            self.distributor.reassign_task(task, alive_peers)

        print(f"[HEALTH] Reassigned {len(pending)} tasks from dead node")

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_node_status(self, node_id: str) -> str:
        with self._lock:
            return self.node_health.get(node_id, {}).get("status", "unknown")

    def get_all_health(self) -> dict:
        with self._lock:
            return dict(self.node_health)

    def get_alive_count(self) -> int:
        with self._lock:
            return sum(
                1 for h in self.node_health.values()
                if h["status"] == "alive"
            )
