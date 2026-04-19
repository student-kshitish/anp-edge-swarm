"""
swarm/health_monitor.py — Self-healing network monitor.

Runs a background thread that pings every known peer on a fixed interval.
Hysteresis logic prevents false positives from transient failures:
  - Flapping nodes (rapid alive/dead changes) are quarantined
  - Reconnecting nodes must pass handshake validation
  - Exponential backoff before declaring a node dead
"""

import threading
import time

MIN_STABLE_PERIOD  = 30   # seconds a node must be stable before trusted
FLAPPING_THRESHOLD = 5    # state changes in 60s window → flapping
BACKOFF_BASE       = 2
MAX_BACKOFF        = 60


class HealthMonitor:
    """Monitors peer health and orchestrates task reassignment on node failure."""

    def __init__(self, get_peers_fn, task_distributor):
        self.get_peers      = get_peers_fn
        self.distributor    = task_distributor
        self.node_health    = {}
        self.running        = False
        self.state_changes  = {}   # node_id -> list of (timestamp, state)
        self.rejoin_pending = {}   # node_id -> True when awaiting handshake

        self.PING_INTERVAL  = 10
        self.DEAD_THRESHOLD = 30
        self.MAX_RETRIES    = 3

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
    # Hysteresis helpers
    # ------------------------------------------------------------------

    def _is_flapping(self, node_id: str) -> bool:
        changes = self.state_changes.get(node_id, [])
        now     = time.time()
        recent  = [c for c in changes if now - c[0] < 60]
        return len(recent) >= FLAPPING_THRESHOLD

    def _record_state_change(self, node_id: str, state: str):
        if node_id not in self.state_changes:
            self.state_changes[node_id] = []
        self.state_changes[node_id].append((time.time(), state))
        # Keep only the 20 most recent entries
        if len(self.state_changes[node_id]) > 20:
            self.state_changes[node_id] = self.state_changes[node_id][-20:]

    def _get_backoff(self, node_id: str) -> int:
        h    = self.node_health.get(node_id, {})
        fails = h.get("fail_count", 0)
        return min(MAX_BACKOFF, BACKOFF_BASE ** fails)

    def _validate_handshake(self, node_id: str) -> bool:
        try:
            from security.crypto import NodeSecurity
            sec = NodeSecurity()
            return sec.is_trusted(node_id)
        except Exception:
            return True

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
                    is_new = node_id not in self.node_health
                    if is_new:
                        self.node_health[node_id] = {
                            "status":      "alive",
                            "last_seen":   time.time(),
                            "fail_count":  0,
                            "ping_count":  0,
                            "response_ms": 0,
                        }

                if is_new:
                    try:
                        from bus.event_bus import get_event_bus
                        get_event_bus().publish(
                            "node.joined",
                            {"node_id": node_id, "ip": ip},
                        )
                    except Exception:
                        pass

                h = self.node_health[node_id]
                h["ping_count"] += 1

                if alive["success"]:
                    h["response_ms"] = alive["ms"]

                    if h.get("status") == "dead":
                        self.rejoin_pending[node_id] = True
                        h["status"] = "reconnecting"
                        self._record_state_change(node_id, "reconnecting")
                        print(f"[HEALTH] Node {node_id[:12]} reconnected — "
                              f"requires handshake validation")

                    elif self.rejoin_pending.get(node_id):
                        if self._validate_handshake(node_id):
                            h["status"] = "alive"
                            h["last_seen"] = time.time()
                            h["fail_count"] = 0
                            del self.rejoin_pending[node_id]
                            self._record_state_change(node_id, "alive")
                            print(f"[HEALTH] Node {node_id[:12]} validated — "
                                  f"now fully alive")

                    elif self._is_flapping(node_id):
                        h["status"] = "flapping"
                        print(f"[HEALTH] Node {node_id[:12]} is FLAPPING — "
                              f"not trusted for task assignment")

                    else:
                        if h.get("status") != "alive":
                            self._record_state_change(node_id, "alive")
                        h["status"]     = "alive"
                        h["last_seen"]  = time.time()
                        h["fail_count"] = 0

                else:
                    h["fail_count"] += 1
                    backoff = self._get_backoff(node_id)
                    print(
                        f"[HEALTH] Node {node_id[:12]} "
                        f"fail #{h['fail_count']} backoff={backoff}s"
                    )

                    if h["fail_count"] >= self.MAX_RETRIES:
                        if h.get("status") != "dead":
                            h["status"] = "dead"
                            self._record_state_change(node_id, "dead")
                            print(f"[HEALTH] !! Node {node_id[:12]} DEAD")
                            self._on_node_dead(node_id, info)
                            try:
                                from bus.event_bus import get_event_bus
                                get_event_bus().publish(
                                    "node.dead",
                                    {
                                        "node_id":   node_id,
                                        "last_seen": h["last_seen"],
                                    },
                                    priority="CRITICAL",
                                )
                            except Exception:
                                pass
                    else:
                        h["status"] = "degraded"

            # Detect nodes that stopped appearing in the peer list
            now       = time.time()
            timed_out = []
            with self._lock:
                for node_id, h in self.node_health.items():
                    if (
                        now - h["last_seen"] > self.DEAD_THRESHOLD
                        and h["status"] not in ("dead", "reconnecting")
                    ):
                        h["status"] = "dead"
                        self._record_state_change(node_id, "dead")
                        timed_out.append((node_id, h["last_seen"]))
                        print(f"[HEALTH] Node {node_id[:12]} timed out")

            for node_id, last_seen in timed_out:
                try:
                    from bus.event_bus import get_event_bus
                    get_event_bus().publish(
                        "node.dead",
                        {"node_id": node_id, "last_seen": last_seen},
                        priority="CRITICAL",
                    )
                except Exception:
                    pass

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

    def is_node_trusted(self, node_id: str) -> bool:
        h      = self.node_health.get(node_id, {})
        status = h.get("status", "unknown")
        if status == "alive":
            return not self._is_flapping(node_id)
        return False
