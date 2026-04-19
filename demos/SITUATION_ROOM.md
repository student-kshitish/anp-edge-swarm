# EdgeMind Situation Room

## Demo Scenario

Three devices coordinate autonomously to monitor a site.
One powerful laptop (brain), one worker laptop, one mobile phone.
Within 30 seconds they discover each other, distribute ML tasks,
and create work orders without any human input.

## Prerequisites

- Victus Linux laptop with Ollama + llama3.2:3b
- Windows or second laptop on same network
- Android phone with Termux and python-psutil
- All devices on the same Wi-Fi network

## The Demo

### Terminal 1 — Victus Brain (start first)

```bash
cd ~/anp-edge-swarm
source venv/bin/activate
PYTHONPATH=. python3 examples/run_bootstrap.py
```

Expected output:
```
[NODE] Identity: a3f9c2... (stable across restarts)
[DHT] Kademlia node started on UDP :6881
[PEER] TCP peer server on :50004
[HEALTH] Self-healing monitor started
[SWARM] Brain node ready — waiting for peers...
```

### Terminal 2 — Victus Brain: Autonomous loop

```bash
source venv/bin/activate
PYTHONPATH=. python3 examples/run_autonomous.py
```

Expected output:
```
[INTENT] Watching for swarm intents...
[SENSOR] Simulating attendance/temperature/materials
[PIPELINE] Distributing ML tasks to available nodes
```

### Terminal 3 — Second Device (Worker)

On the worker laptop/device, set the brain IP:

```bash
cd ~/anp-edge-swarm
source venv/bin/activate
BRAIN_IP=<victus-ip> PYTHONPATH=. python3 examples/run_node.py
```

Expected output:
```
[NODE] Worker identity: b7d1e4...
[PEER] Discovered brain: a3f9c2... at <victus-ip>
[HEALTH] Node a3f9c2 alive (12ms)
[TASK] Received: anomaly_detection — processing...
[TASK] Result sent to brain
```

### Terminal 4 — Android Termux (Phone)

```bash
cd ~/anp-edge-swarm
BRAIN_IP=<victus-ip> python3 examples/run_node.py
```

The phone joins as a low-power worker. Tasks are weighted by benchmark
score so the phone gets lighter workloads.

### Terminal 5 — Topology Snapshot

At any time, capture the live topology:

```bash
source venv/bin/activate
PYTHONPATH=. python3 examples/run_topology.py
```

Expected output:
```
============================================================
  SWARM TOPOLOGY
============================================================
  Generated: 2026-04-19T07:30:00
  Self:      a3f9c2d1e4f5
  Neighbors: 2

  Connection graph:

  [a3f9c2d1e4f5] (self)
  ├── [b7d1e4a2c3f1] 192.168.1.42 worker,ml score=68.3
  └── [c9e2f3b4a1d0] 192.168.1.55 worker score=12.1 

============================================================
```

## What to Watch For

| Time | Event |
|------|-------|
| 0s   | Brain starts, DHT listening |
| 5s   | Worker joins, handshake validated |
| 10s  | Phone joins |
| 15s  | First task distributed to worker |
| 20s  | Anomaly detected → work order created |
| 25s  | Work order visible in `logs/workorders/` |
| 30s  | Kill the worker: brain reassigns tasks automatically |

## Telemetry

Query the black-box recorder from any Python shell:

```python
from agents.telemetry_agent import TelemetryAgent
t = TelemetryAgent()
print(t.get_status())
print(t.query_recent(10))
print(t.query_by_type("node.joined"))
```

## Work Orders

Work orders are written to `logs/workorders/` as JSON files.
Each contains the full decision chain: sensor reading → anomaly →
decision → action plan → execution result.

## Topology DOT Rendering

After running `run_topology.py`, render the graph:

```bash
dot -Tpng logs/topology/topology_*.dot -o topology.png
xdg-open topology.png   # Linux
open topology.png       # macOS
```

Color key:
- Green: self node
- Purple: node with LLM/GPU
- Blue: standard worker
- Gray: low-score node (score < 20)

## Protocol Versioning

All messages carry `anp_version: 1.0.0`. Incompatible nodes
(version outside `1.0.0`–`1.99.99`) are rejected at the protocol
layer before any task assignment.

## Graceful Failure Demo

To test hysteresis:

```bash
# Kill the worker process (Ctrl+C)
# Brain detects failure after 3 pings (~30s)
# Tasks are reassigned to remaining nodes
# Restart worker: it enters "reconnecting" state
# After handshake validation it returns to "alive"
```

If a node toggles alive/dead more than 5 times in 60 seconds,
it is marked "flapping" and excluded from task assignment until stable.
