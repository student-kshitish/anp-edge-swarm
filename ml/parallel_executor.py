"""
ml/parallel_executor.py — Runs assigned tasks in parallel.

Local tasks execute in threads via task_workers.
Remote tasks are dispatched over TCP port 50006 in threads.
"""

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import asdict
from typing import Optional

from ml.task_types import TaskResult, TASKS
from ml.task_workers import (
    run_clean,
    run_anomaly,
    run_trend,
    run_history,
)
from config import MAX_PAYLOAD_BYTES

REMOTE_PORT  = 50006
TASK_TIMEOUT = 15.0


class ParallelExecutor:
    """Execute an assignment plan concurrently across local threads and remote TCP."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, plan: dict, sensor_data: dict, window: list) -> dict:
        futures = {}
        results: dict[str, TaskResult] = {}

        deferred_action = plan.get("action")

        with ThreadPoolExecutor(max_workers=len(TASKS)) as pool:
            for task_type, assignment in plan.items():
                if task_type == "action":
                    continue
                if assignment["local"]:
                    fut = pool.submit(
                        self._run_local_task, task_type, sensor_data, window
                    )
                else:
                    fut = pool.submit(
                        self._send_remote_task,
                        assignment["ip"],
                        task_type,
                        sensor_data,
                        window,
                    )
                futures[fut] = task_type

            deadline = time.time() + TASK_TIMEOUT
            try:
                for fut in as_completed(futures, timeout=max(0.1, deadline - time.time())):
                    task_type = futures[fut]
                    try:
                        results[task_type] = fut.result(timeout=0)
                    except Exception as exc:
                        results[task_type] = self._failed_result(task_type, str(exc))
            except TimeoutError:
                print("[EXECUTOR] Some tasks timed out - using available results")
                for fut, task_type in futures.items():
                    if fut.done():
                        try:
                            results[task_type] = fut.result()
                        except Exception as e:
                            results[task_type] = self._failed_result(task_type, str(e))

        for task_type in TASKS:
            if task_type == "action":
                continue
            if task_type not in results:
                results[task_type] = self._failed_result(task_type, "timeout")

        if deferred_action is not None:
            action_result = self._run_action_task(
                deferred_action,
                results.get("anomaly"),
                results.get("trend"),
                results.get("history"),
                sensor_data,
            )
            results["action"] = action_result

        return results

    # ------------------------------------------------------------------
    # Local dispatch
    # ------------------------------------------------------------------

    def _run_local_task(self, task_type: str,
                        sensor_data: dict, window: list) -> TaskResult:
        workers = {
            "clean":   run_clean,
            "anomaly": run_anomaly,
            "trend":   run_trend,
            "history": run_history,
        }
        fn = workers.get(task_type)
        if fn is None:
            return self._failed_result(task_type, f"No local worker for {task_type}")
        return fn(sensor_data, window)

    def _run_action_task(self, assignment: dict,
                         anomaly_res: Optional[TaskResult],
                         trend_res: Optional[TaskResult],
                         history_res: Optional[TaskResult],
                         sensor_data: dict) -> TaskResult:
        from ml.task_workers import run_action

        anomaly_data  = anomaly_res.result  if anomaly_res  else {}
        trend_data    = trend_res.result    if trend_res    else {}
        history_data  = history_res.result  if history_res  else {}
        context       = str(sensor_data)

        if assignment["local"]:
            return run_action(anomaly_data, trend_data, history_data, context)
        else:
            payload = {
                "task_type":   "action",
                "sensor_data": sensor_data,
                "window":      [],
                "anomaly":     anomaly_data,
                "trend":       trend_data,
                "history":     history_data,
                "context":     context,
            }
            return self._send_remote_payload(assignment["ip"], payload)

    # ------------------------------------------------------------------
    # Remote dispatch
    # ------------------------------------------------------------------

    def _send_remote_task(self, ip: str, task_type: str,
                          sensor_data: dict, window: list) -> TaskResult:
        payload = {
            "task_type":   task_type,
            "sensor_data": sensor_data,
            "window":      window,
        }
        return self._send_remote_payload(ip, payload)

    def _send_remote_payload(self, ip: str, payload: dict) -> TaskResult:
        task_type = payload.get("task_type", "unknown")
        t0 = time.perf_counter()
        try:
            raw = json.dumps(payload).encode("utf-8")
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise ValueError(f"Outgoing payload too large: {len(raw)} bytes")

            with socket.create_connection((ip, REMOTE_PORT), timeout=TASK_TIMEOUT) as sock:
                sock.sendall(len(raw).to_bytes(4, "big") + raw)

                resp_len_bytes = self._recv_exact(sock, 4)
                resp_len = int.from_bytes(resp_len_bytes, "big")
                resp_raw = self._recv_exact(sock, resp_len)

            data = json.loads(resp_raw.decode("utf-8"))
            return TaskResult(
                task_type=data.get("task_type", task_type),
                node_id=data.get("node_id", ip),
                result=data.get("result", {}),
                duration_ms=data.get("duration_ms", (time.perf_counter() - t0) * 1000),
                success=data.get("success", True),
                error=data.get("error"),
            )
        except Exception as exc:
            return TaskResult(
                task_type=task_type,
                node_id=ip,
                result={},
                duration_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                error=str(exc),
            )

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        if n > MAX_PAYLOAD_BYTES:
            raise ValueError(f"Incoming message too large: {n} bytes")
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket closed before all bytes received")
            buf += chunk
        return buf

    @staticmethod
    def _failed_result(task_type: str, reason: str) -> TaskResult:
        return TaskResult(
            task_type=task_type,
            node_id="local",
            result={},
            duration_ms=0.0,
            success=False,
            error=reason,
        )
