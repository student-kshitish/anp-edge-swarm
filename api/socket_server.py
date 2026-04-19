import socket
import json
import threading
import time
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from config import API_HOST, API_PORT, MAX_PAYLOAD_BYTES

_start_time = time.time()
_swarm_mind = None


def set_swarm_mind(mind) -> None:
    global _swarm_mind
    _swarm_mind = mind


# ------------------------------------------------------------------ #
# Helper functions for API endpoints
# ------------------------------------------------------------------ #

def get_swarm_status():
    try:
        from swarm.dht_discovery import get_known_nodes
        from db.db_agent_singleton import get_db
        nodes = get_known_nodes()
        db = get_db()
        return {
            "success": True,
            "uptime_seconds": int(time.time() - _start_time),
            "known_nodes": len(nodes),
            "db_type": db.get_db_type(),
            "total_readings": db.count("sensor_readings"),
            "total_workorders": db.count("work_orders"),
            "total_predictions": db.count("predictions"),
            "autonomous": _swarm_mind is not None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_peers_info():
    try:
        from swarm.dht_discovery import get_known_nodes
        nodes = get_known_nodes()
        peers = []
        for nid, info in nodes.items():
            caps = info.get("caps", info)
            inner = caps.get("caps", caps)
            bench = inner.get("benchmark", {})
            peers.append({
                "node_id": nid[:12],
                "full_id": nid,
                "ip": info.get("addr") or info.get("ip", ""),
                "os": inner.get("os", "unknown"),
                "hostname": inner.get("hostname", ""),
                "roles": inner.get("roles", []),
                "ram_gb": inner.get("ram_gb", 0),
                "cpu_cores": inner.get("cpu_cores", 0),
                "composite_score": bench.get("composite", 0),
                "llm_available": bench.get("llm_available", False),
                "status": "online",
            })
        return {"success": True, "peers": peers, "count": len(peers)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_workorders_list():
    try:
        from db.db_agent_singleton import get_db
        db = get_db()
        orders = db.fetch("work_orders", limit=50)
        return {"success": True, "workorders": orders, "count": len(orders)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_sensor_readings_list():
    try:
        from db.db_agent_singleton import get_db
        db = get_db()
        readings = db.fetch("sensor_readings", limit=100)
        return {"success": True, "readings": readings, "count": len(readings)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_learning_status():
    try:
        try:
            with open(".learned_params.json") as f:
                params = json.load(f)
        except Exception:
            params = {"anomaly_threshold": 2.5, "trust_score": {}}
        return {"success": True, "learned_params": params}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_predictions_list():
    try:
        from db.db_agent_singleton import get_db
        db = get_db()
        preds = db.fetch("predictions", limit=50)
        return {"success": True, "predictions": preds, "count": len(preds)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_recent_events():
    try:
        from bus.event_bus import get_event_bus
        eb = get_event_bus()
        events = eb.get_events(limit=50)
        return {"success": True, "events": events, "count": len(events)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ------------------------------------------------------------------ #
# Request handler
# ------------------------------------------------------------------ #

def handle_client(conn, addr):
    print(f"[SOCKET] Request from {addr}")
    elapsed = 0
    try:
        conn.settimeout(30)
        raw_len = conn.recv(4)
        if not raw_len:
            return
        msg_len = int.from_bytes(raw_len, "big")
        if msg_len > MAX_PAYLOAD_BYTES:
            conn.close()
            print(f"[SOCKET] Rejected oversized request: {msg_len} bytes from {addr}")
            return

        data = b""
        while len(data) < msg_len:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        request      = json.loads(data.decode())
        request_type = request.get("type", "intent")

        if request_type == "status":
            response = get_swarm_status()

        elif request_type == "peers":
            response = get_peers_info()

        elif request_type == "workorders":
            response = get_workorders_list()

        elif request_type == "readings":
            response = get_sensor_readings_list()

        elif request_type == "learning":
            response = get_learning_status()

        elif request_type == "predictions":
            response = get_predictions_list()

        elif request_type == "events":
            response = get_recent_events()

        elif request_type == "db_stats":
            from db.query import get_stats
            response = {"success": True, "stats": get_stats()}

        elif request_type == "db_readings":
            from db.query import get_recent_readings
            sensor_type = request.get("sensor_type")
            limit = int(request.get("limit", 20))
            response = {
                "success": True,
                "readings": get_recent_readings(sensor_type=sensor_type, limit=limit),
            }

        elif request_type == "db_workorders":
            from db.query import get_work_orders
            status = request.get("status", "OPEN")
            response = {
                "success": True,
                "work_orders": get_work_orders(status=status),
            }

        elif request_type == "autonomous_status":
            if _swarm_mind is not None:
                st = _swarm_mind.status()
                response = {
                    "success": True,
                    "uptime_seconds": st["uptime_seconds"],
                    "known_devices": st["known_devices"],
                    "pipeline_cycles": st["pipeline_cycles"],
                    "autonomous": True,
                    "last_action": "work order created",
                    "status": "monitoring",
                }
            else:
                response = {
                    "success": True,
                    "autonomous": False,
                    "status": "idle — autonomous mode not started",
                }

        else:
            user_text = request.get("text", "")
            print(f"[SOCKET] Intent: {user_text}")

            t0 = time.time()

            from core.intent_parser import parse_intent_llm
            from core.orchestrator import run_intent

            intent = parse_intent_llm(user_text)
            result = run_intent(intent, use_llm=False)

            elapsed = int((time.time() - t0) * 1000)

            response = {
                "success": True,
                "intent": intent,
                "summary": result.get("summary", {}),
                "decision": result.get("decision", ""),
                "ml_pipeline": result.get("ml_pipeline", {}),
                "elapsed_ms": elapsed,
            }

    except Exception as e:
        response = {"success": False, "error": str(e)}

    body = json.dumps(response).encode()
    conn.sendall(len(body).to_bytes(4, "big") + body)
    conn.close()
    print(f"[SOCKET] Response sent in {elapsed}ms")


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((API_HOST, API_PORT))
    server.listen(10)
    server.settimeout(2.0)
    print(f"[SOCKET] Python socket server on {API_HOST}:{API_PORT}")

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True,
            ).start()
        except socket.timeout:
            pass


if __name__ == "__main__":
    start_server()
