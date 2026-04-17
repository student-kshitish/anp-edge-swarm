"""
swarm/task_distributor.py — Distribute sensor tasks across discovered swarm nodes.

Port map:
  6881  — DHT discovery (swarm/dht_discovery.py)
  50004 — TASK_ASSIGN  (brain → worker)   TCP
  50005 — TASK_RESULT  (worker → brain)   TCP  ← swarm/result_collector.py

TCP is used for both channels so communication works across the internet,
not just same-LAN UDP broadcast.
"""

import json
import socket
import threading
import time
import uuid
import logging

from swarm.dht_discovery import get_known_nodes
from swarm.capability import get_capabilities

logger = logging.getLogger(__name__)

TASK_PORT   = 50004
RESULT_PORT = 50005

_RETRY_COUNT = 3
_RETRY_DELAY = 1.0   # seconds between retries
_SEND_TIMEOUT = 5.0  # seconds per send attempt


# ------------------------------------------------------------------ #
# distribute_tasks
# ------------------------------------------------------------------ #

def distribute_tasks(intent: dict) -> dict:
    """
    Decide which sensor tasks run locally vs. on remote worker nodes.

    Adds "brain_ip" to every TASK_ASSIGN message so the worker knows
    where to send results back.

    Returns:
        {
            "local_tasks":  ["attendance", ...],
            "remote_tasks": {"node_id": ["temperature", ...], ...}
        }
    """
    data_required: list[str] = intent.get("data_required", [])
    known_nodes = get_known_nodes()
    my_caps = get_capabilities()
    my_id   = my_caps["node_id"]

    worker_peers = {
        nid: info
        for nid, info in known_nodes.items()
        if nid != my_id and "worker" in info["caps"].get("roles", [])
    }

    local_tasks:  list[str]            = []
    remote_tasks: dict[str, list[str]] = {}

    peer_ids  = list(worker_peers.keys())
    peer_index = 0

    for sensor_type in data_required:
        if peer_ids:
            target_id  = peer_ids[peer_index % len(peer_ids)]
            peer_index += 1
            peer_addr  = worker_peers[target_id]["addr"]

            # Determine brain's own IP as seen from this peer's subnet
            brain_ip = _get_local_ip(peer_addr)

            task = {
                "type":        "TASK_ASSIGN",
                "task_id":     str(uuid.uuid4()),
                "sensor_type": sensor_type,
                "report_to":   "orchestrator",
                "assigned_by": my_id,
                "brain_ip":    brain_ip,          # ← worker sends result here
            }

            ok = _tcp_send_with_retry(peer_addr, TASK_PORT, task, target_id)
            if ok:
                remote_tasks.setdefault(target_id, []).append(sensor_type)
                logger.info("[SWARM] Assigned '%s' → %s (%s)", sensor_type, target_id, peer_addr)
            else:
                # Peer unreachable — fall back to local
                logger.warning("[SWARM] Falling back '%s' to local (peer unreachable)", sensor_type)
                local_tasks.append(sensor_type)
        else:
            local_tasks.append(sensor_type)
            logger.info("[SWARM] No worker available, running '%s' locally", sensor_type)

    return {"local_tasks": local_tasks, "remote_tasks": remote_tasks}


# ------------------------------------------------------------------ #
# send_result  (called by worker after collecting a sensor reading)
# ------------------------------------------------------------------ #

def send_result(
    brain_ip:    str,
    task_id:     str,
    sensor_type: str,
    data:        dict,
    from_node:   str,
) -> None:
    """Send a TASK_RESULT TCP packet to brain_ip:50005."""
    msg = {
        "type":        "TASK_RESULT",
        "task_id":     task_id,
        "sensor_type": sensor_type,
        "data":        data,
        "from_node":   from_node,
        "timestamp":   time.time(),
    }
    ok = _tcp_send_with_retry(brain_ip, RESULT_PORT, msg, node_id="brain")
    if not ok:
        logger.warning("[SWARM] Could not deliver result for '%s' to brain %s", sensor_type, brain_ip)


# ------------------------------------------------------------------ #
# listen_for_tasks  (worker side)
# ------------------------------------------------------------------ #

def listen_for_tasks(on_task_received) -> None:
    """
    Start a daemon thread listening on TCP port 50004 for TASK_ASSIGN messages.

    Args:
        on_task_received: callable(task: dict) invoked for every valid task.
    """
    t = threading.Thread(
        target=_task_listen_loop,
        args=(on_task_received,),
        daemon=True,
        name="task-listener",
    )
    t.start()
    logger.info("[SWARM] Task listener started on TCP port %d", TASK_PORT)


def _task_listen_loop(on_task_received) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", TASK_PORT))
    server.listen(10)
    server.settimeout(2.0)

    while True:
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5.0)
                chunks = []
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
            if not data:
                continue
            msg = json.loads(data.decode())
            if msg.get("type") != "TASK_ASSIGN":
                continue
            sensor_type = msg.get("sensor_type", "?")
            assigned_by = msg.get("assigned_by", "?")
            print(f"[SWARM] Task received: {sensor_type} from {assigned_by}", flush=True)
            on_task_received(msg)
        except socket.timeout:
            pass
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Task listener error: %s", e)


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _get_local_ip(peer_addr: str) -> str:
    """Return this machine's LAN IP as seen from the direction of *peer_addr*."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((peer_addr, 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _tcp_send_with_retry(addr: str, port: int, msg: dict, node_id: str = "?") -> bool:
    """
    Send *msg* as JSON to addr:port via TCP.

    TCP gives reliable, ordered delivery and works across the internet
    (unlike UDP broadcast which is LAN-only).

    Retries up to _RETRY_COUNT times with _RETRY_DELAY seconds between attempts.
    Returns True if the message was delivered successfully.
    """
    payload = json.dumps(msg).encode()
    last_error: Exception | None = None

    for attempt in range(1, _RETRY_COUNT + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(_SEND_TIMEOUT)
                sock.connect((addr, port))
                sock.sendall(payload)
            return True
        except OSError as e:
            last_error = e
            logger.debug(
                "[SWARM] TCP send attempt %d/%d to %s:%d failed: %s",
                attempt, _RETRY_COUNT, addr, port, e,
            )
            if attempt < _RETRY_COUNT:
                time.sleep(_RETRY_DELAY)

    print(
        f"[WARN] Node {node_id} unreachable after {_RETRY_COUNT} retries "
        f"({addr}:{port}) — {last_error}",
        flush=True,
    )
    return False


# ------------------------------------------------------------------ #
# TaskDistributor — stateful class for health-monitor integration
# ------------------------------------------------------------------ #

class TaskDistributor:
    """
    Stateful wrapper around distribute_tasks that tracks in-flight assignments
    so HealthMonitor can retrieve and reassign them when a peer dies.
    """

    def __init__(self):
        # task_id → {type, node_id, assigned_at, sensor_type}
        self._active_tasks: dict[str, dict] = {}
        self._lock = __import__("threading").Lock()

    # ------------------------------------------------------------------
    # Active-task bookkeeping (called by distribute_tasks wrapper)
    # ------------------------------------------------------------------

    def record_task(
        self,
        task_id:     str,
        task_type:   str,
        node_id:     str,
        sensor_type: str,
    ) -> None:
        with self._lock:
            self._active_tasks[task_id] = {
                "type":        task_type,
                "node_id":     node_id,
                "assigned_at": __import__("time").time(),
                "sensor_type": sensor_type,
            }

    def complete_task(self, task_id: str) -> None:
        with self._lock:
            self._active_tasks.pop(task_id, None)

    # ------------------------------------------------------------------
    # Health-monitor API
    # ------------------------------------------------------------------

    def get_pending_tasks(self, node_id: str) -> list:
        """Return all tasks currently assigned to *node_id* that haven't completed."""
        with self._lock:
            return [
                {"task_id": tid, **info}
                for tid, info in self._active_tasks.items()
                if info["node_id"] == node_id
            ]

    def reassign_task(self, task: dict, alive_peers: dict) -> None:
        """Pick the best available peer by benchmark score and re-send the task."""
        task_id = task.get("task_id", "unknown")

        # Score each candidate peer — prefer high composite benchmark
        def _peer_score(peer_info: dict) -> float:
            inner = peer_info.get("caps", peer_info)
            bench = inner.get("benchmark", {})
            composite = bench.get("composite", 0)
            if composite > 0:
                return composite
            ram  = float(inner.get("ram_gb",    0))
            cpu  = float(inner.get("cpu_cores", 0))
            return ram * 2.0 + cpu * 1.5

        best_id   = max(alive_peers, key=lambda pid: _peer_score(alive_peers[pid]))
        best_info = alive_peers[best_id]
        best_addr = best_info.get("addr") or best_info.get("ip", "")

        reassign_msg = {
            "type":        "TASK_ASSIGN",
            "task_id":     task_id,
            "sensor_type": task.get("sensor_type", ""),
            "report_to":   "orchestrator",
            "reassigned":  True,
        }

        ok = _tcp_send_with_retry(best_addr, TASK_PORT, reassign_msg, best_id)

        if ok:
            with self._lock:
                if task_id in self._active_tasks:
                    self._active_tasks[task_id]["node_id"] = best_id
            print(f"[SWARM] Task {task_id[:8]} reassigned to {best_id[:12]}")
        else:
            logger.warning(
                "[SWARM] Reassignment of task %s failed — peer %s unreachable",
                task_id[:8], best_id[:12],
            )

    def run_locally(self, task: dict) -> None:
        """Execute *task* on this node as a last-resort fallback."""
        task_type   = task.get("type", "unknown")
        sensor_type = task.get("sensor_type", "")
        print(f"[SWARM] Running {task_type} locally (fallback)")

        try:
            from ml.task_workers import (
                run_clean, run_anomaly, run_trend, run_history, run_action,
            )
            _LOCAL_RUNNERS = {
                "clean":   lambda: run_clean({}, []),
                "anomaly": lambda: run_anomaly({}, []),
                "trend":   lambda: run_trend({}, []),
                "history": lambda: run_history({}, []),
                "action":  lambda: run_action({}, {}, {}, sensor_type),
            }
            runner = _LOCAL_RUNNERS.get(task_type)
            if runner:
                result = runner()
                logger.info(
                    "[SWARM] Local fallback for %s completed: success=%s",
                    task_type, result.success,
                )
            else:
                logger.warning("[SWARM] No local runner for task type: %s", task_type)
        except Exception as exc:
            logger.error("[SWARM] Local fallback for %s failed: %s", task_type, exc)
