# ANP — Agent Networking Protocol v1.0

## Overview

ANP is a lightweight, JSON-based message protocol for heterogeneous agent swarms.
Any agent written in any language that produces and consumes messages conforming
to this specification can join an EdgeMind swarm without modification.

Design goals:
- **Language-agnostic** — JSON over TCP; no Python-specific serialisation
- **Transport-agnostic** — works over raw TCP sockets, WebSockets, or MQTT
- **Extensible** — `payload` is opaque per `msg_type`; new types don't break old agents
- **Self-describing** — every message carries its version and type

---

## Message Format

Every ANP message is a JSON object with the following top-level fields:

```json
{
  "anp_version": "1.0",
  "msg_id":      "550e8400-e29b-41d4-a716-446655440000",
  "msg_type":    "SENSOR_READING",
  "sender_id":   "a3f2c1d4e5b6a7f8c9d0e1f2a3b4c5d6e7f8a9b0",
  "receiver_id": "broadcast",
  "timestamp":   1713254400.123,
  "priority":    "MEDIUM",
  "reply_to":    null,
  "task_id":     "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "payload":     {},
  "signature":   null
}
```

| Field         | Type            | Required | Description |
|---------------|-----------------|----------|-------------|
| `anp_version` | string          | yes      | Protocol version; reject messages with unknown versions |
| `msg_id`      | string (UUID4)  | yes      | Unique per message; use for deduplication |
| `msg_type`    | string (enum)   | yes      | One of the defined message types below |
| `sender_id`   | string (40 hex) | yes      | SHA-1 node identity of the sending agent |
| `receiver_id` | string (40 hex) | no       | Target node ID or `"broadcast"` |
| `timestamp`   | float           | yes      | Unix timestamp (seconds with fractional ms) |
| `priority`    | string (enum)   | no       | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` (default `MEDIUM`) |
| `reply_to`    | string (UUID4)  | no       | `msg_id` of the message this is replying to |
| `task_id`     | string (UUID4)  | no       | Groups related messages (assign → result) |
| `payload`     | object          | yes      | Message-type-specific content |
| `signature`   | string \| null  | no       | Reserved for future authentication; always `null` in v1.0 |

---

## Message Types

### Discovery

#### `ANNOUNCE`
Broadcast by a node at startup and periodically to advertise its capabilities.

```json
{
  "msg_type": "ANNOUNCE",
  "payload": {
    "node_id":   "a3f2c1d4...",
    "addr":      "192.168.1.42",
    "roles":     ["brain", "worker"],
    "ram_gb":    16,
    "cpu_cores": 8,
    "benchmark": {
      "composite":     72.4,
      "cpu_score":     85.0,
      "mem_score":     91.2,
      "llm_tps":       14.3,
      "llm_available": true,
      "disk_score":    78.5,
      "net_latency_ms": 12
    }
  }
}
```

#### `PING` / `PONG`
Health probe. Receiver should respond with `PONG` and set `reply_to` to the `PING` `msg_id`.

```json
{ "msg_type": "PING", "payload": {} }
{ "msg_type": "PONG", "payload": { "uptime_sec": 3600 }, "reply_to": "<ping-msg-id>" }
```

---

### Task Lifecycle

#### `TASK_ASSIGN`
Brain sends to a worker to request execution of one analysis task.

```json
{
  "msg_type": "TASK_ASSIGN",
  "payload": {
    "task_type":   "anomaly",
    "sensor_data": { "temperature": 38.2, "humidity": 61 },
    "window":      [{ "temperature": 22.1 }, { "temperature": 23.4 }],
    "brain_ip":    "192.168.1.1",
    "timeout_sec": 15
  }
}
```

#### `TASK_ACCEPT`
Worker acknowledges it will execute the task.

```json
{
  "msg_type": "TASK_ACCEPT",
  "task_id":  "<same-task-id>",
  "payload":  { "eta_sec": 3 }
}
```

#### `TASK_REJECT`
Worker declines the task (overloaded, capability mismatch, etc.).

```json
{
  "msg_type": "TASK_REJECT",
  "task_id":  "<same-task-id>",
  "payload":  { "reason": "LLM_UNAVAILABLE" }
}
```

#### `TASK_RESULT`
Worker sends completed results back to brain.

```json
{
  "msg_type": "TASK_RESULT",
  "task_id":  "<same-task-id>",
  "payload": {
    "task_type":  "anomaly",
    "result": {
      "anomalies":     [{ "field": "temperature", "value": 95.0, "severity": "CRITICAL" }],
      "anomaly_count": 1,
      "status":        "CRITICAL"
    },
    "elapsed_ms": 42,
    "success":    true,
    "error":      null
  }
}
```

#### `TASK_FAILED`
Worker reports unrecoverable task failure.

```json
{
  "msg_type": "TASK_FAILED",
  "task_id":  "<same-task-id>",
  "payload":  { "reason": "timeout", "elapsed_ms": 15000 }
}
```

---

### Agent Communication

#### `SENSOR_READING`
Raw sensor data from a sensor agent.

```json
{
  "msg_type": "SENSOR_READING",
  "payload": {
    "sensor_type": "temperature",
    "value":       38.2,
    "unit":        "°C",
    "status":      "WARNING",
    "raw":         { "probe_id": "T01", "voltage": 2.47 },
    "location":    null
  }
}
```

#### `ANOMALY_ALERT`
Anomaly agent detected a significant deviation.

```json
{
  "msg_type": "ANOMALY_ALERT",
  "priority": "CRITICAL",
  "payload": {
    "anomaly_type": "temperature_spike",
    "field":        "temperature",
    "value":        95.0,
    "expected":     22.5,
    "deviation":    72.5,
    "description":  "Temperature 72.5°C above baseline — possible fire",
    "auto_action":  true
  }
}
```

#### `ACTION_REQUEST`
Action agent requests execution of a corrective action.

```json
{
  "msg_type": "ACTION_REQUEST",
  "priority": "CRITICAL",
  "payload": {
    "action_type":  "fire_suppression",
    "urgency":      "CRITICAL",
    "description":  "Activate sprinkler system in Zone 3",
    "data":         { "zone": 3, "duration_sec": 60 },
    "auto_execute": true
  }
}
```

#### `ACTION_CONFIRM`
Confirms an action was executed.

```json
{
  "msg_type": "ACTION_CONFIRM",
  "payload": {
    "action_type": "fire_suppression",
    "executed_at": 1713254403.0,
    "outcome":     "success",
    "details":     "Sprinkler Zone 3 activated"
  }
}
```

---

### System Messages

#### `HEARTBEAT`
Periodic keepalive to prevent timeout-based dead declarations.

```json
{ "msg_type": "HEARTBEAT", "payload": { "load_pct": 42 } }
```

#### `DB_SYNC`
Gossip protocol payload for distributed database synchronisation.

```json
{
  "msg_type": "DB_SYNC",
  "payload": {
    "records":    [{ "id": 1, "table": "sensor_readings", "data": {} }],
    "from_ts":    1713254300.0,
    "to_ts":      1713254400.0
  }
}
```

#### `INTENT`
Brain publishes the current sensor data intent (what data it needs).

```json
{
  "msg_type": "INTENT",
  "payload": {
    "data_required": ["temperature", "humidity", "motion"],
    "window_size":   10,
    "context":       "factory_floor_sensor_run"
  }
}
```

---

## Priority Levels

| Priority   | Use case |
|------------|----------|
| `LOW`      | Periodic housekeeping, non-urgent telemetry |
| `MEDIUM`   | Normal sensor readings and task results |
| `HIGH`     | Anomaly alerts, degraded node warnings |
| `CRITICAL` | Fire / flood / safety events requiring immediate action |

---

## Implementation Guide

Any language can implement an ANP agent. The minimum requirements are:

### 1. Generate a stable `node_id`

Derive a 40-character lowercase hex string (SHA-1) from stable machine
identifiers — MAC address, hostname, and a random seed stored to disk.
The seed ensures the same ID survives reboots.

```python
# Python example
import hashlib, uuid, socket
raw = f"{uuid.getnode()}-{socket.gethostname()}-{stored_seed}"
node_id = hashlib.sha1(raw.encode()).hexdigest()  # 40 hex chars
```

```go
// Go example
import ("crypto/sha1"; "fmt"; "net")
h := sha1.New()
h.Write([]byte(macAddr + hostname + storedSeed))
nodeID := fmt.Sprintf("%x", h.Sum(nil))
```

### 2. Connect to the bootstrap node

The bootstrap node listens on TCP port 50000.  
Open a persistent TCP connection and send an `ANNOUNCE` message immediately.

### 3. Send `ANNOUNCE`

```json
{
  "anp_version": "1.0",
  "msg_id":      "<uuid4>",
  "msg_type":    "ANNOUNCE",
  "sender_id":   "<your-node-id>",
  "receiver_id": "broadcast",
  "timestamp":   <unix-float>,
  "priority":    "MEDIUM",
  "reply_to":    null,
  "task_id":     "<uuid4>",
  "payload": {
    "node_id":   "<your-node-id>",
    "addr":      "<your-lan-ip>",
    "roles":     ["worker"],
    "ram_gb":    8,
    "cpu_cores": 4,
    "benchmark": { "composite": 0 }
  },
  "signature": null
}
```

### 4. Receive and respond to `TASK_ASSIGN`

Listen on TCP port 50004 for incoming connections.  
For each connection, read the full JSON payload, validate it, execute the task,
then send a `TASK_RESULT` back to `payload.brain_ip:50005`.

```python
# Pseudocode
msg = deserialize(conn.recv())
valid, reason = validate_message(msg)
if not valid or msg["msg_type"] != "TASK_ASSIGN":
    return

result = run_task(msg["payload"]["task_type"], msg["payload"])
response = build_task_result(
    sender_id  = MY_NODE_ID,
    task_id    = msg["task_id"],
    task_type  = msg["payload"]["task_type"],
    result     = result,
    elapsed_ms = elapsed,
    success    = True,
)
send_to(msg["payload"]["brain_ip"], 50005, serialize(response))
```

### 5. Send `TASK_RESULT` to brain

Connect to `brain_ip:50005`, send the serialised `TASK_RESULT` message, close.

---

## Port Map

| Port  | Direction          | Purpose |
|-------|--------------------|---------|
| 50000 | any → bootstrap    | Node registration and peer discovery |
| 50004 | brain → worker     | `TASK_ASSIGN` delivery |
| 50005 | worker → brain     | `TASK_RESULT` delivery |
| 50010 | health-monitor → any | TCP ping probe (health monitor) |

---

## Example: Fire Alert Scenario

The following shows the exact packet sequence when a temperature sensor reading
triggers a fire alert and the system takes automatic action.

### Step 1 — SensorAgent sends `SENSOR_READING`

```json
{
  "anp_version": "1.0",
  "msg_id":      "aaa00001-0000-0000-0000-000000000001",
  "msg_type":    "SENSOR_READING",
  "sender_id":   "sensor_node_id_40chars_hexstring00000",
  "receiver_id": "broadcast",
  "timestamp":   1713254400.0,
  "priority":    "MEDIUM",
  "reply_to":    null,
  "task_id":     "task-0001-0000-0000-0000-000000000001",
  "payload": {
    "sensor_type": "temperature",
    "value":       95.0,
    "unit":        "°C",
    "status":      "CRITICAL",
    "raw":         { "probe_id": "T01", "adc": 4095 },
    "location":    "server_room_zone3"
  },
  "signature": null
}
```

### Step 2 — AnomalyAgent detects the spike and sends `ANOMALY_ALERT`

```json
{
  "anp_version": "1.0",
  "msg_id":      "aaa00002-0000-0000-0000-000000000002",
  "msg_type":    "ANOMALY_ALERT",
  "sender_id":   "anomaly_node_id_40chars_hexstring0000",
  "receiver_id": "broadcast",
  "timestamp":   1713254400.5,
  "priority":    "CRITICAL",
  "reply_to":    "aaa00001-0000-0000-0000-000000000001",
  "task_id":     "task-0001-0000-0000-0000-000000000001",
  "payload": {
    "anomaly_type": "temperature_spike",
    "field":        "temperature",
    "value":        95.0,
    "expected":     22.5,
    "deviation":    72.5,
    "description":  "Temperature 72.5°C above baseline — possible fire in zone3",
    "auto_action":  true
  },
  "signature": null
}
```

### Step 3 — ActionAgent receives `ANOMALY_ALERT` and sends `ACTION_REQUEST`

```json
{
  "anp_version": "1.0",
  "msg_id":      "aaa00003-0000-0000-0000-000000000003",
  "msg_type":    "ACTION_REQUEST",
  "sender_id":   "action_node_id_40chars_hexstring00000",
  "receiver_id": "broadcast",
  "timestamp":   1713254401.0,
  "priority":    "CRITICAL",
  "reply_to":    "aaa00002-0000-0000-0000-000000000002",
  "task_id":     "task-0001-0000-0000-0000-000000000001",
  "payload": {
    "action_type":  "fire_suppression",
    "urgency":      "CRITICAL",
    "description":  "Activate sprinkler system in server_room_zone3 immediately",
    "data": {
      "zone":         "server_room_zone3",
      "duration_sec": 60,
      "notify":       ["on-call-engineer", "fire-department"]
    },
    "auto_execute": true
  },
  "signature": null
}
```

### Step 4 — ActionAgent executes and sends `ACTION_CONFIRM`

```json
{
  "anp_version": "1.0",
  "msg_id":      "aaa00004-0000-0000-0000-000000000004",
  "msg_type":    "ACTION_CONFIRM",
  "sender_id":   "action_node_id_40chars_hexstring00000",
  "receiver_id": "broadcast",
  "timestamp":   1713254401.8,
  "priority":    "CRITICAL",
  "reply_to":    "aaa00003-0000-0000-0000-000000000003",
  "task_id":     "task-0001-0000-0000-0000-000000000001",
  "payload": {
    "action_type": "fire_suppression",
    "executed_at": 1713254401.8,
    "outcome":     "success",
    "details":     "Sprinkler Zone 3 activated; notifications sent to 2 contacts"
  },
  "signature": null
}
```

Total latency from sensor reading to action confirmation: **1.8 seconds**.

---

## Validation Rules

Implementations MUST reject messages that:
- Are missing any required field
- Have `anp_version` ≠ `"1.0"`
- Have an unknown `msg_type`

Implementations SHOULD:
- Ignore unknown fields (forward compatibility)
- Log and discard malformed messages rather than crashing
- Respond to `PING` with `PONG` within 3 seconds

---

## Versioning

The protocol version is `"1.0"`. Future versions will increment the minor number
for backwards-compatible additions and the major number for breaking changes.
Agents that receive a message with a version they do not recognise should
respond with `TASK_REJECT` citing `"VERSION_UNSUPPORTED"` as the reason.
