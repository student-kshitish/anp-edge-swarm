"""
ml/inference_server.py — TCP server on port 50006.

Receives task requests from remote nodes, runs the appropriate
task_workers function, and sends the result back.

Call start_server() once; it runs the listener in a daemon thread
and handles multiple concurrent connections via a thread pool.
"""

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from ml.task_types import TaskResult
from ml.task_workers import (
    run_clean,
    run_anomaly,
    run_trend,
    run_history,
    run_action,
)

INFERENCE_PORT = 50006
_MAX_WORKERS   = 10
_RECV_TIMEOUT  = 10.0  # seconds

_WORKERS = {
    "clean":   run_clean,
    "anomaly": run_anomaly,
    "trend":   run_trend,
    "history": run_history,
}

_server_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_server(host: str = "0.0.0.0", port: int = INFERENCE_PORT) -> None:
    """Start the inference TCP server in a background daemon thread."""
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        return  # already running

    _server_thread = threading.Thread(
        target=_serve_forever,
        args=(host, port),
        daemon=True,
        name="inference-server",
    )
    _server_thread.start()
    print(f"[INFERENCE] Server listening on {host}:{port}")


# ---------------------------------------------------------------------------
# Internal server loop
# ---------------------------------------------------------------------------

def _serve_forever(host: str, port: int) -> None:
    pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS,
                              thread_name_prefix="inference-worker")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(32)
        while True:
            try:
                conn, addr = srv.accept()
                pool.submit(_handle_connection, conn, addr)
            except Exception:
                pass


def _handle_connection(conn: socket.socket, addr) -> None:
    with conn:
        conn.settimeout(_RECV_TIMEOUT)
        try:
            # Read length-prefixed request
            raw_len = _recv_exact(conn, 4)
            msg_len = int.from_bytes(raw_len, "big")
            raw_msg = _recv_exact(conn, msg_len)

            payload    = json.loads(raw_msg.decode("utf-8"))
            task_type  = payload.get("task_type", "unknown")
            sensor_data = payload.get("sensor_data", {})
            window     = payload.get("window", [])

            print(f"[INFERENCE] Received {task_type} from {addr[0]}:{addr[1]}")
            t0 = time.perf_counter()

            result: TaskResult = _dispatch(task_type, payload, sensor_data, window)

            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(f"[INFERENCE] Completed {task_type} in {elapsed_ms:.1f}ms")

            # Send length-prefixed response
            resp = json.dumps(asdict(result)).encode("utf-8")
            conn.sendall(len(resp).to_bytes(4, "big") + resp)

        except Exception as exc:
            # Best-effort error response
            try:
                err_result = TaskResult(
                    task_type="unknown",
                    node_id=socket.gethostname(),
                    result={},
                    duration_ms=0.0,
                    success=False,
                    error=str(exc),
                )
                resp = json.dumps(asdict(err_result)).encode("utf-8")
                conn.sendall(len(resp).to_bytes(4, "big") + resp)
            except Exception:
                pass


def _dispatch(task_type: str, payload: dict,
              sensor_data: dict, window: list) -> TaskResult:
    if task_type == "action":
        return run_action(
            payload.get("anomaly", {}),
            payload.get("trend",   {}),
            payload.get("history", {}),
            payload.get("context", ""),
        )
    fn = _WORKERS.get(task_type)
    if fn:
        return fn(sensor_data, window)
    return TaskResult(
        task_type=task_type,
        node_id=socket.gethostname(),
        result={},
        duration_ms=0.0,
        success=False,
        error=f"Unknown task type: {task_type}",
    )


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed before all bytes received")
        buf += chunk
    return buf
