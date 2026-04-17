import platform
import psutil
import json


def get_capabilities() -> dict:
    caps = {
        "node_id":   platform.node(),
        "os":        platform.system(),
        "cpu_cores": psutil.cpu_count(),
        "ram_gb":    round(psutil.virtual_memory().total / 1e9, 1),
        "roles":     detect_roles(),
    }

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
    roles = ["worker"]
    ram   = psutil.virtual_memory().total / 1e9
    if ram > 8:
        roles.append("brain")
    try:
        import torch
        if torch.cuda.is_available():
            roles.append("gpu")
    except ImportError:
        pass
    return roles


if __name__ == "__main__":
    print(json.dumps(get_capabilities(), indent=2))
