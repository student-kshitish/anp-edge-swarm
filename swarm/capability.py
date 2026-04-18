import platform
import json


def _is_termux() -> bool:
    import os
    return os.path.exists("/data/data/com.termux")


def _safe_cpu_count() -> int:
    try:
        import psutil
        return psutil.cpu_count() or 1
    except Exception:
        import os
        return os.cpu_count() or 1


def _safe_ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if "MemTotal" in line:
                        kb = int(line.split()[1])
                        return round(kb / (1024 * 1024), 1)
        except Exception:
            pass
        return 2.0


def _safe_os_name() -> str:
    if _is_termux():
        return "Android"
    return platform.system()


def _safe_ollama_check() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return len(r.json().get("models", [])) > 0
    except Exception:
        return False


def get_node_id() -> str:
    return platform.node()


def get_capabilities() -> dict:
    caps = {
        "node_id":        get_node_id(),
        "hostname":       platform.node(),
        "os":             _safe_os_name(),
        "cpu_cores":      _safe_cpu_count(),
        "ram_gb":         _safe_ram_gb(),
        "roles":          [],
        "ollama_running": _safe_ollama_check(),
        "is_mobile":      _is_termux(),
    }

    if caps["ram_gb"] >= 8:
        caps["roles"].append("brain")
        caps["roles"].append("worker")
    elif caps["ram_gb"] >= 4:
        caps["roles"].append("worker")
    else:
        caps["roles"].append("sensor")

    if caps["ollama_running"]:
        caps["roles"].append("inference")

    if caps["is_mobile"]:
        caps["roles"].append("mobile")

    try:
        import torch
        if torch.cuda.is_available():
            caps["roles"].append("gpu")
    except ImportError:
        pass

    try:
        from swarm.benchmark import run_benchmarks
        bench = run_benchmarks()
        caps["benchmark"] = {
            "cpu_score":      bench.get("cpu_score",      0),
            "mem_score":      bench.get("mem_score",      0),
            "llm_tps":        bench.get("llm_tps",        0),
            "llm_available":  bench.get("llm_available",  False),
            "disk_score":     bench.get("disk_score",     0),
            "net_latency_ms": bench.get("net_latency_ms", 999),
            "composite":      bench.get("composite",      0),
        }
    except Exception:
        caps["benchmark"] = {"composite": 0}

    return caps


def detect_roles() -> list:
    return get_capabilities()["roles"]


if __name__ == "__main__":
    print(json.dumps(get_capabilities(), indent=2))
