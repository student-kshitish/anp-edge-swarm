# Windows: run as admin:
# netsh advfirewall firewall add rule name="EdgeMind Results" protocol=TCP dir=in localport=50005 action=allow

"""
swarm/result_collector.py — Collects TASK_RESULT TCP packets sent back by worker nodes.

Workers send results to brain_ip:50005 after completing a sensor task.
TCP is used so results are delivered reliably across the internet.

Message format:
    {
        "type":        "TASK_RESULT",
        "task_id":     "<uuid>",
        "sensor_type": "attendance|temperature|materials",
        "data":        { <sensor reading dict> },
        "from_node":   "<node_id>",
        "timestamp":   <float epoch>
    }
"""

import json
import socket
import threading
import time
import logging

logger = logging.getLogger(__name__)

RESULT_PORT = 50005

_results: dict[str, dict] = {}      # task_id -> full result message
_lock = threading.Lock()
_arrived = threading.Event()         # pulsed each time a new result arrives
_listening = False


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def start_listening() -> None:
    """Start the result-collector daemon thread (idempotent)."""
    global _listening
    if _listening:
        return
    _listening = True
    t = threading.Thread(target=_listen_loop, daemon=True, name="result-collector")
    t.start()
    logger.info("[RESULT] Collector listening on TCP port %d", RESULT_PORT)


def get_results() -> dict:
    """Return a snapshot of all collected results keyed by task_id."""
    with _lock:
        return dict(_results)


def wait_for_results(expected_count: int, timeout: float = 15.0) -> list:
    """
    Block until *expected_count* results have arrived, or *timeout* seconds pass.

    Returns the list of collected result dicts (may be fewer than expected_count
    if the timeout fires first).
    """
    deadline = time.time() + timeout
    while True:
        with _lock:
            current = list(_results.values())
        if len(current) >= expected_count:
            return current
        remaining = deadline - time.time()
        if remaining <= 0:
            logger.warning(
                "[RESULT] Timeout waiting for results — got %d/%d",
                len(current), expected_count,
            )
            return current
        # Wait for next arrival event (pulse), then re-check
        _arrived.wait(timeout=min(1.0, remaining))
        _arrived.clear()


# ------------------------------------------------------------------ #
# Internal
# ------------------------------------------------------------------ #

def _listen_loop() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", RESULT_PORT))
    server.listen(10)
    server.settimeout(2.0)

    while True:
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5.0)
                chunks = []
                while True:
                    chunk = conn.recv(65535)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
            if not data:
                continue
            msg = json.loads(data.decode())
            if msg.get("type") != "TASK_RESULT":
                continue
            task_id     = msg.get("task_id", "unknown")
            sensor_type = msg.get("sensor_type", "?")
            from_node   = msg.get("from_node", "?")
            print(f"[RESULT] Received {sensor_type} from {from_node}", flush=True)
            with _lock:
                _results[task_id] = msg
            _arrived.set()
        except socket.timeout:
            pass
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("[RESULT] Collector error: %s", e)
