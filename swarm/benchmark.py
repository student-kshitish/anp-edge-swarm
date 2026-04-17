"""
swarm/benchmark.py — Actual performance benchmarks, not just hardware specs.

Results are cached for CACHE_TTL seconds so the benchmarks only run once
per hour even if get_capabilities() is called frequently.
"""

import json
import math
import os
import time

from swarm.node_identity import get_node_id

BENCHMARK_FILE = ".benchmark_cache"
CACHE_TTL      = 3600  # re-run benchmarks every hour


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_benchmarks() -> dict:
    cached = _load_cache()
    if cached:
        print("[BENCH] Using cached benchmark results")
        return cached

    print("[BENCH] Running performance benchmarks...")
    results = {}

    results["cpu_score"]     = _bench_cpu()
    results["mem_score"]     = _bench_memory()
    results["llm_tps"]       = _bench_ollama()
    results["llm_available"] = results["llm_tps"] > 0
    results["disk_score"]    = _bench_disk()
    results["net_latency_ms"] = _bench_network()

    results["node_id"]   = get_node_id()
    results["timestamp"] = time.time()
    results["composite"] = _composite_score(results)

    _save_cache(results)
    print(f"[BENCH] Composite score: {results['composite']:.1f}")
    return results


# ---------------------------------------------------------------------------
# Individual benchmarks
# ---------------------------------------------------------------------------

def _bench_cpu() -> float:
    t0   = time.time()
    size = 200
    a = [[math.sin(i * j + 1) for j in range(size)] for i in range(size)]
    b = [[math.cos(i * j + 1) for j in range(size)] for i in range(size)]
    # Full matrix multiply — deliberately Python-only to measure raw CPU speed
    _ = [
        [sum(a[i][k] * b[k][j] for k in range(size)) for j in range(size)]
        for i in range(size)
    ]
    elapsed = time.time() - t0
    score   = max(0.0, 100 - elapsed * 50)
    print(f"[BENCH] CPU score: {score:.1f} ({elapsed:.2f}s)")
    return round(score, 2)


def _bench_memory() -> float:
    t0      = time.time()
    data    = list(range(1_000_000))
    _       = sum(data)
    elapsed = time.time() - t0
    score   = max(0.0, 100 - elapsed * 1000)
    print(f"[BENCH] Memory score: {score:.1f}")
    return round(score, 2)


def _bench_ollama() -> float:
    try:
        import requests
        t0 = time.time()
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model":  "llama3.2:3b",
                "prompt": "Count to 5:",
                "stream": False,
            },
            timeout=30,
        )
        elapsed = time.time() - t0
        result  = resp.json()
        tokens  = result.get("eval_count", 10)
        tps     = tokens / elapsed if elapsed > 0 else 0.0
        print(f"[BENCH] Ollama: {tps:.1f} tokens/sec")
        return round(tps, 2)
    except Exception:
        print("[BENCH] Ollama: not available")
        return 0.0


def _bench_disk() -> float:
    t0   = time.time()
    path = ".bench_tmp"
    data = b"x" * 1024 * 1024  # 1 MB
    try:
        with open(path, "wb") as f:
            f.write(data)
        with open(path, "rb") as f:
            _ = f.read()
    finally:
        if os.path.exists(path):
            os.remove(path)
    elapsed = time.time() - t0
    score   = max(0.0, 100 - elapsed * 100)
    print(f"[BENCH] Disk score: {score:.1f}")
    return round(score, 2)


def _bench_network() -> float:
    import socket
    try:
        t0   = time.time()
        sock = socket.create_connection(("8.8.8.8", 53), timeout=3)
        sock.close()
        ms = int((time.time() - t0) * 1000)
        print(f"[BENCH] Network latency: {ms}ms")
        return float(ms)
    except Exception:
        return 999.0


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def _composite_score(r: dict) -> float:
    score = (
        r.get("cpu_score",  0)  * 0.30
        + r.get("mem_score",  0) * 0.20
        + r.get("disk_score", 0) * 0.10
        + min(r.get("llm_tps", 0) * 5, 100) * 0.35
        + max(0, 100 - r.get("net_latency_ms", 999)) * 0.05
    )
    return round(score, 2)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        if not os.path.exists(BENCHMARK_FILE):
            return {}
        with open(BENCHMARK_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > CACHE_TTL:
            return {}
        return data
    except Exception:
        return {}


def _save_cache(data: dict):
    with open(BENCHMARK_FILE, "w") as f:
        json.dump(data, f, indent=2)
