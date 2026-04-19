"""
swarm/visualize.py — Topology visualization for the EdgeMind swarm.

Collects neighbor lists from the DHT and generates a Graphviz DOT file
plus an ASCII diagram showing the current mesh topology.
"""

import json
import os
import time
from datetime import datetime

from swarm.node_identity import get_node_id
from swarm.dht_discovery import get_known_nodes
from bus.event_bus import get_event_bus


def get_my_neighbors() -> dict:
    nodes   = get_known_nodes()
    my_id   = get_node_id()
    neighbors = {}

    for nid, info in nodes.items():
        caps  = info.get("caps", info)
        inner = caps.get("caps", caps)
        bench = inner.get("benchmark", {})
        neighbors[nid] = {
            "ip":     info.get("addr") or info.get("ip", ""),
            "os":     inner.get("os", "unknown"),
            "roles":  inner.get("roles", []),
            "score":  bench.get("composite", 0),
            "llm":    bench.get("llm_available", False),
            "ram_gb": inner.get("ram_gb", 0),
        }

    return {
        "node_id":   my_id,
        "timestamp": time.time(),
        "neighbors": neighbors,
        "count":     len(neighbors),
    }


def generate_dot(topology: dict, output_file: str = "topology.dot") -> str:
    my_id     = topology["node_id"]
    neighbors = topology["neighbors"]

    lines = [
        "digraph EdgeMindSwarm {",
        '  rankdir=LR;',
        '  node [shape=box, style=filled, fontname="Helvetica"];',
        '  bgcolor="transparent";',
        "",
    ]

    lines.append(
        f'  "{my_id[:12]}" [label="{my_id[:12]}\\n(self)", '
        f'fillcolor="#10b981", fontcolor="white"];'
    )

    for nid, info in neighbors.items():
        roles = ",".join(info.get("roles", [])[:2])
        score = info.get("score", 0)
        llm   = "GPU" if info.get("llm") else ""

        color = "#3b82f6"
        if info.get("llm"):
            color = "#a855f7"
        elif score < 20:
            color = "#6b7280"

        label = (
            f"{nid[:12]}\\n{info['ip']}\\n"
            f"{roles} {llm}\\nscore={score:.1f}"
        )
        lines.append(
            f'  "{nid[:12]}" [label="{label}", '
            f'fillcolor="{color}", fontcolor="white"];'
        )

    for nid in neighbors:
        lines.append(
            f'  "{my_id[:12]}" -> "{nid[:12]}" '
            f'[color="#10b981", penwidth=2];'
        )

    lines.append("}")

    dot_content = "\n".join(lines)
    with open(output_file, "w") as f:
        f.write(dot_content)

    print(f"[TOPOLOGY] DOT file written: {output_file}")
    print(f"[TOPOLOGY] Render with: dot -Tpng {output_file} -o topology.png")
    return output_file


def generate_ascii_diagram(topology: dict) -> str:
    my_id     = topology["node_id"]
    neighbors = topology["neighbors"]

    lines = [
        "=" * 60,
        "  SWARM TOPOLOGY",
        "=" * 60,
        f"  Generated: {datetime.now().isoformat()}",
        f"  Self:      {my_id[:12]}",
        f"  Neighbors: {len(neighbors)}",
        "",
        "  Connection graph:",
        "",
        f"  [{my_id[:12]}] (self)",
    ]

    items = list(neighbors.items())
    for i, (nid, info) in enumerate(items):
        is_last = i == len(items) - 1
        prefix  = "  └──" if is_last else "  ├──"
        roles   = ",".join(info.get("roles", [])[:2])
        score   = info.get("score", 0)
        llm     = "[LLM]" if info.get("llm") else ""
        lines.append(
            f"{prefix} [{nid[:12]}] {info['ip']} "
            f"{roles} score={score:.1f} {llm}"
        )

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def publish_topology():
    topology = get_my_neighbors()
    try:
        eb = get_event_bus()
        eb.publish("topology.update", topology, sender_id=get_node_id())
    except Exception:
        pass
    return topology


def save_snapshot(output_dir: str = "logs/topology") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    topology = get_my_neighbors()
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")

    dot_path  = f"{output_dir}/topology_{ts}.dot"
    json_path = f"{output_dir}/topology_{ts}.json"

    generate_dot(topology, dot_path)
    with open(json_path, "w") as f:
        json.dump(topology, f, indent=2)

    print(generate_ascii_diagram(topology))
    return {"dot": dot_path, "json": json_path, "data": topology}
