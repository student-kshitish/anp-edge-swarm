"""
swarm/task_distributor.py — Distribute sensor tasks across discovered swarm nodes.

NOTE: Uses UDP port 50002 for TASK_ASSIGN messages.
      Port 50001 is already taken by swarm/discovery.py for peer announcements.
"""

import json
import socket
import threading
import uuid
import logging

from swarm.discovery import get_known_nodes
from swarm.capability import get_capabilities

logger = logging.getLogger(__name__)

TASK_PORT = 50002   # separate from discovery's BROADCAST_PORT (50001)


# ------------------------------------------------------------------ #
# distribute_tasks
# ------------------------------------------------------------------ #

def distribute_tasks(intent: dict) -> dict:
    """
    Decide which sensor tasks run locally vs. on remote worker nodes.

    Args:
        intent: parsed intent dict; must contain "data_required" list.

    Returns:
        {
            "local_tasks":  ["attendance", ...],
            "remote_tasks": {"node_id": ["temperature", ...], ...}
        }
    """
    data_required: list[str] = intent.get("data_required", [])
    known_nodes = get_known_nodes()
    my_id = get_capabilities()["node_id"]

    # Collect worker peers (exclude self, just in case)
    worker_peers = {
        nid: info
        for nid, info in known_nodes.items()
        if nid != my_id and "worker" in info["caps"].get("roles", [])
    }

    local_tasks: list[str] = []
    remote_tasks: dict[str, list[str]] = {}

    # Simple round-robin: cycle through available workers
    peer_ids = list(worker_peers.keys())
    peer_index = 0

    for sensor_type in data_required:
        if peer_ids:
            target_id = peer_ids[peer_index % len(peer_ids)]
            peer_index += 1

            task = {
                "type": "TASK_ASSIGN",
                "task_id": str(uuid.uuid4()),
                "sensor_type": sensor_type,
                "report_to": "orchestrator",
                "assigned_by": my_id,
            }
            peer_addr = worker_peers[target_id]["addr"]
            _send_task(peer_addr, task)

            remote_tasks.setdefault(target_id, []).append(sensor_type)
            logger.info("[SWARM] Assigned '%s' → %s (%s)", sensor_type, target_id, peer_addr)
        else:
            local_tasks.append(sensor_type)
            logger.info("[SWARM] No worker available, running '%s' locally", sensor_type)

    return {"local_tasks": local_tasks, "remote_tasks": remote_tasks}


def _send_task(peer_addr: str, task: dict) -> None:
    """Fire-and-forget UDP send of a TASK_ASSIGN message."""
    payload = json.dumps(task).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, (peer_addr, TASK_PORT))


# ------------------------------------------------------------------ #
# listen_for_tasks
# ------------------------------------------------------------------ #

def listen_for_tasks(on_task_received) -> None:
    """
    Start a daemon thread that listens on UDP port 50002 for TASK_ASSIGN messages.

    Args:
        on_task_received: callable(task: dict) called for every valid task received.
    """
    t = threading.Thread(
        target=_task_listen_loop,
        args=(on_task_received,),
        daemon=True,
        name="task-listener",
    )
    t.start()
    logger.info("[SWARM] Task listener started on UDP port %d", TASK_PORT)


def _task_listen_loop(on_task_received) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", TASK_PORT))
    sock.settimeout(2.0)

    while True:
        try:
            data, _ = sock.recvfrom(4096)
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
