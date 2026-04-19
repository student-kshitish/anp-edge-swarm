"""
ml/task_workers.py — Five specialised worker functions.

Each function takes clean sensor data and a sliding window list,
performs its analysis using only the standard library + math,
and returns a TaskResult.
"""

import math
import json
import time
import socket
import urllib.request
import urllib.error
from typing import Optional

from ml.task_types import TaskResult
from config import OLLAMA_BASE_URL, OLLAMA_MODEL

# Cache hostname once at module load — avoid a syscall on every task
_NODE_ID: str = "local"
try:
    _NODE_ID = socket.gethostname()
except Exception:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field_stats(window: list) -> dict[str, dict]:
    """Compute mean/std per numeric field across the window."""
    fields: dict[str, list] = {}
    for reading in window:
        for key, val in reading.items():
            if isinstance(val, (int, float)):
                fields.setdefault(key, []).append(float(val))
    stats = {}
    for name, values in fields.items():
        n    = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
        std  = math.sqrt(variance)
        stats[name] = {"mean": mean, "std": std, "values": values}
    return stats


# ---------------------------------------------------------------------------
# Task 1 — Clean
# ---------------------------------------------------------------------------

def run_clean(data: dict, window: list) -> TaskResult:
    """Remove None values (replace with window average) and clip outliers."""
    t0 = time.perf_counter()
    try:
        stats   = _field_stats(window) if window else {}
        cleaned = {}
        for key, val in data.items():
            if val is None:
                cleaned[key] = stats[key]["mean"] if key in stats else 0
            elif isinstance(val, (int, float)):
                mean = stats[key]["mean"] if key in stats else val
                std  = stats[key]["std"]  if key in stats else 0
                if std > 0:
                    low  = mean - 3 * std
                    high = mean + 3 * std
                    cleaned[key] = max(low, min(high, float(val)))
                else:
                    cleaned[key] = float(val)
            else:
                cleaned[key] = val

        return TaskResult(
            task_type="clean",
            node_id=_NODE_ID,
            result=cleaned,
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=True,
        )
    except Exception as exc:
        return TaskResult(
            task_type="clean",
            node_id=_NODE_ID,
            result={},
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Task 2 — Anomaly detection
# ---------------------------------------------------------------------------

def run_anomaly(data: dict, window: list) -> TaskResult:
    """Flag values beyond 2.5 std from window mean."""
    t0 = time.perf_counter()
    try:
        stats     = _field_stats(window) if window else {}
        anomalies = []
        THRESHOLD = 2.5

        for key, val in data.items():
            if not isinstance(val, (int, float)):
                continue
            if key not in stats:
                continue
            mean = stats[key]["mean"]
            std  = stats[key]["std"]
            if std == 0:
                continue
            z = abs(float(val) - mean) / std
            if z > THRESHOLD:
                severity = "CRITICAL" if z > 4.0 else "HIGH" if z > 3.0 else "MEDIUM"
                anomalies.append({
                    "field":    key,
                    "value":    val,
                    "expected": round(mean, 3),
                    "z_score":  round(z, 3),
                    "severity": severity,
                })

        count  = len(anomalies)
        status = "OK" if count == 0 else (
            "CRITICAL" if any(a["severity"] == "CRITICAL" for a in anomalies) else "WARNING"
        )

        return TaskResult(
            task_type="anomaly",
            node_id=_NODE_ID,
            result={"anomalies": anomalies, "anomaly_count": count, "status": status},
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=True,
        )
    except Exception as exc:
        return TaskResult(
            task_type="anomaly",
            node_id=_NODE_ID,
            result={"anomalies": [], "anomaly_count": 0, "status": "UNKNOWN"},
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Task 3 — Trend (linear regression, math only)
# ---------------------------------------------------------------------------

def _linear_regression(values: list[float]):
    n = len(values)
    if n < 2:
        return 0.0, values[0] if values else 0.0
    xs     = list(range(n))
    sum_x  = sum(xs)
    sum_y  = sum(values)
    sum_xy = sum(x * y for x, y in zip(xs, values))
    sum_xx = sum(x * x for x in xs)
    denom  = n * sum_xx - sum_x ** 2
    if denom == 0:
        return 0.0, sum_y / n
    slope     = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def run_trend(data: dict, window: list) -> TaskResult:
    """Linear regression per numeric field; predict value at reading +10."""
    t0 = time.perf_counter()
    try:
        stats  = _field_stats(window) if window else {}
        trends = {}
        STABLE_THRESHOLD = 0.05

        for key, info in stats.items():
            values = info["values"]
            slope, intercept = _linear_regression(values)
            n = len(values)
            predicted_next = intercept + slope * (n + 10)

            if abs(slope) < STABLE_THRESHOLD:
                direction = "STABLE"
            elif slope > 0:
                direction = "RISING"
            else:
                direction = "FALLING"

            trends[key] = {
                "slope":          round(slope, 4),
                "direction":      direction,
                "predicted_next": round(predicted_next, 3),
            }

        return TaskResult(
            task_type="trend",
            node_id=_NODE_ID,
            result={"trends": trends},
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=True,
        )
    except Exception as exc:
        return TaskResult(
            task_type="trend",
            node_id=_NODE_ID,
            result={"trends": {}},
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Task 4 — History matching (cosine similarity, no external libs)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: dict, b: dict) -> float:
    keys = (
        set(k for k, v in a.items() if isinstance(v, (int, float))) &
        set(k for k, v in b.items() if isinstance(v, (int, float)))
    )
    if not keys:
        return 0.0
    dot   = sum(float(a[k]) * float(b[k]) for k in keys)
    mag_a = math.sqrt(sum(float(a[k]) ** 2 for k in keys))
    mag_b = math.sqrt(sum(float(b[k]) ** 2 for k in keys))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def run_history(data: dict, window: list) -> TaskResult:
    t0 = time.perf_counter()
    try:
        from db.db_agent_singleton import get_db
        db   = get_db()
        rows = db.get_history(limit=50)

        entries = []
        for row in rows:
            raw = row.get("raw_json")
            if not raw:
                continue
            try:
                assembled   = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            sensor_data = assembled.get("clean_data", {})
            entries.append({
                "sensor_data": sensor_data,
                "outcome":     row.get("status", ""),
                "timestamp":   row.get("timestamp", ""),
            })

        if not entries:
            return TaskResult(
                task_type="history",
                node_id=_NODE_ID,
                result={"matched": False},
                duration_ms=(time.perf_counter() - t0) * 1000,
                success=True,
            )

        best_score = -1.0
        best_entry = None
        for entry in entries:
            score = _cosine_similarity(data, entry.get("sensor_data", {}))
            if score > best_score:
                best_score = score
                best_entry = entry

        past_outcome = best_entry.get("outcome", "") if best_entry else ""
        matched_date = best_entry.get("timestamp", "")[:10] if best_entry else ""

        return TaskResult(
            task_type="history",
            node_id=_NODE_ID,
            result={
                "matched":        best_score > 0.5,
                "similarity":     round(best_score, 4),
                "matched_date":   matched_date,
                "past_outcome":   past_outcome,
                "recommendation": f"Based on past outcome: {past_outcome}" if past_outcome else "",
            },
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=True,
        )
    except Exception as exc:
        return TaskResult(
            task_type="history",
            node_id=_NODE_ID,
            result={"matched": False},
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Task 5 — Action (Ollama LLM call)
# ---------------------------------------------------------------------------

def run_action(anomaly_result: dict, trend_result: dict,
               history_result: dict, context: str) -> TaskResult:
    """Build a prompt and call Ollama for a recommended action."""
    t0 = time.perf_counter()

    prompt = (
        "You are a site monitoring AI.\n"
        f"Anomalies detected: {json.dumps(anomaly_result)}\n"
        f"Current trends: {json.dumps(trend_result)}\n"
        f"Historical match: {json.dumps(history_result)}\n"
        f"Context: {context}\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "action": "specific action to take",\n'
        '  "urgency": "LOW/MEDIUM/HIGH/CRITICAL",\n'
        '  "reason": "one sentence explanation",\n'
        '  "notify": ["list of who to notify"]\n'
        "}"
    )

    payload = json.dumps({
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        raw_text = body.get("response", "").strip()
        start    = raw_text.find("{")
        end      = raw_text.rfind("}") + 1
        action_data = json.loads(raw_text[start:end]) if start != -1 else {}

        return TaskResult(
            task_type="action",
            node_id=_NODE_ID,
            result=action_data,
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=True,
        )
    except Exception as exc:
        fallback = {
            "action": "Manual review required — LLM unavailable",
            "urgency": "MEDIUM",
            "reason": str(exc),
            "notify": ["on-call"],
        }
        return TaskResult(
            task_type="action",
            node_id=_NODE_ID,
            result=fallback,
            duration_ms=(time.perf_counter() - t0) * 1000,
            success=False,
            error=str(exc),
        )
