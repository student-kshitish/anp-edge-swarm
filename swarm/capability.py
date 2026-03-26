import platform
import psutil
import json

def get_capabilities():
    return {
        "node_id": platform.node(),
        "os": platform.system(),
        "cpu_cores": psutil.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "roles": detect_roles()
    }

def detect_roles():
    roles = ["worker"]
    ram = psutil.virtual_memory().total / 1e9
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
    print(json.dumps(get_capabilities(), indent=2))# swarm/capability.py
