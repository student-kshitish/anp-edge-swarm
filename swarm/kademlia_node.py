"""
swarm/kademlia_node.py — Full Kademlia DHT node over UDP.

Port: 6881 (default)

Message types (all JSON over UDP):
  PING        {type, sender_id, sender_ip, sender_port}
  PONG        {type, sender_id, cap}
  FIND_NODE   {type, sender_id, sender_ip, sender_port, target_id, cap}
  FOUND_NODES {type, sender_id, nodes: [[id,ip,port],...], cap}
  STORE       {type, sender_id, key, value}
  FIND_VALUE  {type, sender_id, key}
  VALUE       {type, sender_id, key, value}
  ANNOUNCE    {type, sender_id, cap}
"""

import json
import socket
import threading
import time

from swarm.node_identity import get_node_id
from swarm.kbucket import RoutingTable, K

PORT = 6881
MAX_PACKET = 65535
STALE_TIMEOUT = 90      # seconds before a node is considered dead
REFRESH_INTERVAL = 30   # seconds between refresh cycles


def _own_ip() -> str:
    """Best-guess outbound IP of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class KademliaNode:
    def __init__(self):
        self.node_id: str = get_node_id()
        self.routing_table: RoutingTable = RoutingTable(self.node_id)
        self.storage: dict = {}                 # key -> value string
        self.known_peers: dict = {}             # node_id -> cap dict
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT not available on Windows — skip it
        if hasattr(socket, 'SO_REUSEPORT'):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._running: bool = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self, bootstrap_ip: str = None, bootstrap_port: int = PORT) -> None:
        """
        Bind UDP socket, start background threads, optionally bootstrap.
        """
        try:
            self._sock.bind(("0.0.0.0", PORT))
            print(f"[KADEMLIA] Socket bound to 0.0.0.0:{PORT}")
        except OSError as e:
            print(f"[KADEMLIA] ERROR binding to port {PORT}: {e}")
            print(f"[KADEMLIA] Try: sudo lsof -i udp:{PORT}")
            raise
        self._sock.settimeout(2.0)
        self._running = True

        threading.Thread(
            target=self._listen_loop, daemon=True, name="kademlia-listen"
        ).start()
        threading.Thread(
            target=self._refresh_loop, daemon=True, name="kademlia-refresh"
        ).start()

        if bootstrap_ip:
            print(f"[KADEMLIA] Sending FIND_NODE to bootstrap {bootstrap_ip}:{bootstrap_port}")
            self._send(bootstrap_ip, bootstrap_port, {
                "type": "FIND_NODE",
                "sender_id": self.node_id,
                "sender_ip": _own_ip(),
                "sender_port": PORT,
                "target_id": self.node_id,
                "cap": self._own_cap(),
            })
            print(f"[KADEMLIA] Bootstrap message sent")

        print(f"[KADEMLIA] Node {self.node_id[:12]} started on port 6881", flush=True)

    def announce_self(self) -> None:
        """Broadcast own capability to all known nodes and store in DHT."""
        cap = self._own_cap()
        for node in self.routing_table.all_nodes():
            _, nip, nport, _ = node
            self._send(nip, nport, {
                "type": "ANNOUNCE",
                "sender_id": self.node_id,
                "cap": cap,
            })
        self.store(self.node_id, json.dumps(cap))

    def find_peer(self, node_id: str) -> dict:
        """
        Send FIND_VALUE to closest known nodes, wait 2 s, return result.
        Returns capability dict or {} if not found.
        """
        closest = self.routing_table.find_closest(node_id, K)
        for node in closest:
            _, nip, nport, _ = node
            self._send(nip, nport, {
                "type": "FIND_VALUE",
                "sender_id": self.node_id,
                "key": node_id,
            })
        time.sleep(2)
        raw = self.storage.get(node_id)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def get_all_peers(self) -> dict:
        result = {}
        for node_id, caps in self.known_peers.items():
            result[node_id] = {
                "node_id": node_id,
                "caps": caps,
                "addr": caps.get("ip", "unknown") if isinstance(caps, dict) else "unknown",
                "roles": caps.get("roles", ["worker"]) if isinstance(caps, dict) else ["worker"],
                "last_seen": time.time()
            }
        return result

    def store(self, key: str, value_str: str) -> None:
        """Store locally and replicate to K closest nodes."""
        self.storage[key] = value_str
        closest = self.routing_table.find_closest(key, K)
        for node in closest:
            _, nip, nport, _ = node
            self._send(nip, nport, {
                "type": "STORE",
                "sender_id": self.node_id,
                "key": key,
                "value": value_str,
            })

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------ #
    # Internal loops                                                       #
    # ------------------------------------------------------------------ #

    def _listen_loop(self) -> None:
        while self._running:
            try:
                data, addr = self._sock.recvfrom(MAX_PACKET)

                # Filter non-JSON binary packets silently
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    # Binary packet - not our protocol, ignore silently
                    continue

                # Filter packets not starting with {
                text = text.strip()
                if not text.startswith("{"):
                    continue

                msg = json.loads(text)

                # Filter packets without our required fields
                if "type" not in msg:
                    continue

                self._handle(msg, addr)

            except json.JSONDecodeError:
                pass  # ignore silently
            except socket.timeout:
                continue
            except OSError:
                break   # socket closed on stop()
            except Exception as e:
                if self._running:
                    print(f"[KADEMLIA] Error: {e}", flush=True)

    def _refresh_loop(self) -> None:
        while self._running:
            time.sleep(REFRESH_INTERVAL)
            if not self._running:
                break
            # Announce own capability to all known nodes
            self.announce_self()
            # Ping all live nodes; evict stale ones
            now = time.time()
            own = _own_ip()
            for node in self.routing_table.all_nodes():
                nid, nip, nport, last_seen = node
                if now - last_seen > STALE_TIMEOUT:
                    continue   # will be cleaned by evict_stale below
                self._send(nip, nport, {
                    "type": "PING",
                    "sender_id": self.node_id,
                    "sender_ip": own,
                    "sender_port": PORT,
                })
            self.routing_table.evict_stale(STALE_TIMEOUT)

    # ------------------------------------------------------------------ #
    # Message handler                                                      #
    # ------------------------------------------------------------------ #

    def _handle(self, msg: dict, addr) -> None:
        sender_id = msg.get("sender_id")
        sender_ip = msg.get("sender_ip", addr[0])
        sender_port = msg.get("sender_port", addr[1])

        # Always add sender to routing table
        if sender_id:
            self.routing_table.add_node(sender_id, sender_ip, sender_port)

        # Track capability if present
        cap = msg.get("cap")
        if cap and sender_id:
            self.known_peers[sender_id] = cap

        mtype = msg.get("type")

        if mtype == "PING":
            self._send(sender_ip, sender_port, {
                "type": "PONG",
                "sender_id": self.node_id,
                "cap": self._own_cap(),
            })

        elif mtype == "PONG":
            if sender_id:
                self.routing_table.add_node(sender_id, addr[0], addr[1])

        elif mtype == "FIND_NODE":
            if sender_id:
                self.known_peers.setdefault(sender_id, msg.get("cap") or {})
                self.routing_table.add_node(sender_id, addr[0], addr[1])
            target_id = msg.get("target_id", self.node_id)
            closest = self.routing_table.find_closest(target_id, K)
            nodes = [[n[0], n[1], n[2]] for n in closest]
            self._send(sender_ip, sender_port, {
                "type": "FOUND_NODES",
                "sender_id": self.node_id,
                "nodes": nodes,
                "cap": self._own_cap(),
            })

        elif mtype == "FOUND_NODES":
            own = _own_ip()
            for entry in msg.get("nodes", []):
                if len(entry) < 3:
                    continue
                nid, nip, nport = entry[0], entry[1], int(entry[2])
                if nid == self.node_id:
                    continue
                self.known_peers.setdefault(nid, {"ip": nip, "port": nport})
                self.routing_table.add_node(nid, nip, nport)
                print(f"[KADEMLIA] Discovered {nid[:12]} @ {nip}", flush=True)
                # Walk towards target to populate routing table
                self._send(nip, nport, {
                    "type": "FIND_NODE",
                    "sender_id": self.node_id,
                    "sender_ip": own,
                    "sender_port": PORT,
                    "target_id": self.node_id,
                    "cap": self._own_cap(),
                })

        elif mtype == "STORE":
            key = msg.get("key")
            value = msg.get("value")
            if key is not None:
                self.storage[key] = value

        elif mtype == "FIND_VALUE":
            key = msg.get("key")
            if key in self.storage:
                self._send(sender_ip, sender_port, {
                    "type": "VALUE",
                    "sender_id": self.node_id,
                    "key": key,
                    "value": self.storage[key],
                })
            else:
                closest = self.routing_table.find_closest(key if key else self.node_id, K)
                nodes = [[n[0], n[1], n[2]] for n in closest]
                self._send(sender_ip, sender_port, {
                    "type": "FOUND_NODES",
                    "sender_id": self.node_id,
                    "nodes": nodes,
                })

        elif mtype == "VALUE":
            key = msg.get("key")
            value = msg.get("value")
            if key is not None:
                self.storage[key] = value

        elif mtype == "ANNOUNCE":
            ann_cap = msg.get("cap")
            if ann_cap and sender_id:
                self.known_peers[sender_id] = ann_cap
                self.routing_table.add_node(sender_id, addr[0], addr[1])
                nid_display = (
                    ann_cap.get("node_id", sender_id)
                    if isinstance(ann_cap, dict)
                    else sender_id
                )
                print(f"[KADEMLIA] Peer announced: {str(nid_display)[:12]}", flush=True)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _own_cap(self) -> dict:
        from swarm.capability import get_capabilities
        return get_capabilities()

    def _send(self, ip: str, port: int, msg: dict) -> None:
        try:
            data = json.dumps(msg).encode("utf-8")
            self._sock.sendto(data, (ip, port))
            print(f"[KADEMLIA] -> {msg.get('type')} to {ip}:{port}", flush=True)
        except Exception as e:
            print(f"[KADEMLIA] Send error to {ip}:{port}: {e}", flush=True)
