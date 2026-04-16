import socket
import json
import threading
import time
import sys
import os

sys.path.insert(0, os.path.abspath("."))

HOST = "127.0.0.1"
PORT = 9000

# Holds a SwarmMind instance when autonomous mode is active.
# Set by run_autonomous.py via set_swarm_mind().
_swarm_mind = None


def set_swarm_mind(mind) -> None:
    """Register the active SwarmMind so status queries can reach it."""
    global _swarm_mind
    _swarm_mind = mind


def handle_client(conn, addr):
    print(f"[SOCKET] Request from {addr}")
    elapsed = 0
    try:
        # Read 4-byte length prefix
        raw_len = conn.recv(4)
        if not raw_len:
            return
        msg_len = int.from_bytes(raw_len, "big")

        # Read full message
        data = b""
        while len(data) < msg_len:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        request = json.loads(data.decode())

        # ------------------------------------------------------------------ #
        # Route: database queries
        # ------------------------------------------------------------------ #
        if request.get("type") == "db_stats":
            from db.query import get_stats
            response = {"success": True, "stats": get_stats()}

        elif request.get("type") == "db_readings":
            from db.query import get_recent_readings
            sensor_type = request.get("sensor_type")
            limit       = int(request.get("limit", 20))
            response = {
                "success":  True,
                "readings": get_recent_readings(sensor_type=sensor_type, limit=limit),
            }

        elif request.get("type") == "db_workorders":
            from db.query import get_work_orders
            status = request.get("status", "OPEN")
            response = {
                "success":     True,
                "work_orders": get_work_orders(status=status),
            }

        # ------------------------------------------------------------------ #
        # Route: autonomous status query
        # ------------------------------------------------------------------ #
        elif request.get("type") == "autonomous_status":
            if _swarm_mind is not None:
                st = _swarm_mind.status()
                response = {
                    "success":         True,
                    "uptime_seconds":  st["uptime_seconds"],
                    "known_devices":   st["known_devices"],
                    "pipeline_cycles": st["pipeline_cycles"],
                    "autonomous":      True,
                    "last_action":     "work order created",
                    "status":          "monitoring",
                }
            else:
                response = {
                    "success":    True,
                    "autonomous": False,
                    "status":     "idle — autonomous mode not started",
                }

        # ------------------------------------------------------------------ #
        # Route: normal intent query
        # ------------------------------------------------------------------ #
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
                "success":     True,
                "intent":      intent,
                "summary":     result.get("summary", {}),
                "decision":    result.get("decision", ""),
                "ml_pipeline": result.get("ml_pipeline", {}),
                "elapsed_ms":  elapsed,
            }

    except Exception as e:
        response = {
            "success": False,
            "error":   str(e)
        }

    # Send response with 4-byte length prefix
    body = json.dumps(response).encode()
    conn.sendall(len(body).to_bytes(4, "big") + body)
    conn.close()
    print(f"[SOCKET] Response sent in {elapsed}ms")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(10)
    print(f"[SOCKET] Python socket server on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        threading.Thread(
            target=handle_client,
            args=(conn, addr),
            daemon=True
        ).start()

if __name__ == "__main__":
    start_server()
