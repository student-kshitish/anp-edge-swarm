import sys, os, time, argparse
sys.path.insert(0, os.path.abspath("."))

from swarm.dht_discovery import start as start_discovery
from swarm.peer_server import start_server as start_peer_server
from swarm.peer_client import exchange_with_all
from swarm.known_peers import PEER_IPS
from ml.inference_server import start_server as start_inference_server
from api.socket_server import start_server as start_socket_server
import threading

parser = argparse.ArgumentParser()
parser.add_argument("--bootstrap", default=None)
args = parser.parse_args()

print("=" * 50)
print("  EdgeMind API Node")
print("=" * 50)

start_discovery(bootstrap_ip=args.bootstrap)
start_peer_server()
exchange_with_all(PEER_IPS)
start_inference_server()

print("[API] All swarm components started")
print("[API] Starting Python socket server on port 9000...")
print("[API] Start Rust HTTP server separately:")
print("[API]   cd ~/edgemind-api && cargo run")
print("[API] Then send requests:")
print('[API]   curl -X POST http://localhost:8000/intent \\')
print('[API]     -H "Content-Type: application/json" \\')
print('[API]     -d \'{"text": "check all sensors"}\'')

threading.Thread(target=start_socket_server, daemon=False).start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopped")
