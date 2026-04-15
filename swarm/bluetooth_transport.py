"""
swarm/bluetooth_transport.py — Bluetooth peer discovery via BLE scan + RFCOMM.

Discovery strategy (no BLE advertising required):

  1. BleakScanner discovers all nearby Bluetooth devices every 15 s.
  2. For each unseen device, a background thread attempts an RFCOMM
     connection on RFCOMM_PORT (classic Bluetooth, supported on all laptops).
  3. On connect, both sides exchange their capability JSON.
     If the remote node carries a "node_id" key it is treated as an
     EdgeMind peer and stored in known_bt_peers.
  4. An RFCOMM server thread runs in parallel to accept incoming probes
     from other EdgeMind nodes performing the same scan.

This approach requires no platform-specific BLE advertising and works on
both Linux and Windows.  bleak is still used for scanning only.

Fallback: if bleak is not installed, start() returns False and the rest
of the swarm continues on WiFi/DHT without any exception.
"""

import asyncio
import json
import socket
import threading
import time

from swarm.capability import get_capabilities
from swarm.node_identity import get_node_id

RFCOMM_PORT = 3


class BluetoothTransport:

    def __init__(self):
        self.node_id        = get_node_id()
        self.known_bt_peers = {}   # BT address -> peer info dict
        self.running        = False
        self._callbacks     = []   # on_message(raw: bytes, addr: str)
        self._loop          = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, on_message=None) -> bool:
        """Start BLE scanning and RFCOMM server in background threads.

        Returns True on success, False if bleak is unavailable.
        """
        try:
            import bleak  # noqa: F401 — presence check only
        except ImportError:
            print("[BT] bleak not installed — pip install bleak")
            return False

        if on_message:
            self._callbacks.append(on_message)

        self.running = True
        self._loop   = asyncio.new_event_loop()

        # BLE scan loop (asyncio, dedicated event loop)
        threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="bt-transport",
        ).start()

        # RFCOMM server (blocking accept loop, own thread)
        threading.Thread(
            target=self.start_rfcomm_server,
            daemon=True,
            name="bt-rfcomm-server",
        ).start()

        print("[BT] Bluetooth transport started")
        return True

    def send_message(self, message: dict):
        """Send a message dict to every known peer via RFCOMM."""
        for addr in list(self.known_bt_peers.keys()):
            threading.Thread(
                target=self._send_rfcomm,
                args=(addr, message),
                daemon=True,
            ).start()

    def get_known_peers(self) -> dict:
        return dict(self.known_bt_peers)

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # BLE scan (asyncio)
    # ------------------------------------------------------------------

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        await self._scan_loop()

    async def _scan_loop(self):
        from bleak import BleakScanner
        while self.running:
            try:
                devices = await BleakScanner.discover(timeout=5.0)
                for device in devices:
                    addr = device.address
                    if addr not in self.known_bt_peers:
                        print(f"[BT] Found device: {device.name} ({addr})")
                        # Probe in a background thread so the scan loop
                        # is never blocked by a slow RFCOMM handshake.
                        threading.Thread(
                            target=self._try_rfcomm_connect,
                            args=(addr,),
                            daemon=True,
                        ).start()
            except Exception as e:
                print(f"[BT] Scan error: {e}")
            await asyncio.sleep(15)

    # ------------------------------------------------------------------
    # RFCOMM outbound (client side)
    # ------------------------------------------------------------------

    def _try_rfcomm_connect(self, addr: str):
        """Attempt an RFCOMM handshake with a device found by BLE scan.

        Silently discards devices that are not running an EdgeMind node.
        """
        bt_sock = None
        try:
            bt_sock = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM,
            )
            bt_sock.settimeout(5)
            bt_sock.connect((addr, RFCOMM_PORT))

            # Send our capabilities first
            cap = get_capabilities()
            cap["node_id"] = self.node_id
            bt_sock.send(json.dumps(cap).encode())

            # Read the remote node's capabilities
            data     = bt_sock.recv(4096)
            peer_cap = json.loads(data.decode())

            peer_id = peer_cap.get("node_id")
            if peer_id and peer_id != self.node_id:
                self.known_bt_peers[addr] = {
                    "address":   addr,
                    "node_id":   peer_id,
                    "caps":      peer_cap,
                    "last_seen": time.time(),
                }
                print(f"[BT] Connected to EdgeMind peer: {peer_id[:12]} @ {addr}")
                for cb in self._callbacks:
                    cb(json.dumps(peer_cap).encode(), addr)
        except Exception:
            pass  # Not an EdgeMind node or not reachable — ignore silently
        finally:
            if bt_sock:
                try:
                    bt_sock.close()
                except Exception:
                    pass

    def add_static_peer(self, mac: str, node_id: str):
        """Manually register a peer by Bluetooth MAC and node ID.

        Useful when the remote MAC is already known (e.g. printed on the
        device) so RFCOMM discovery does not need to probe first.
        """
        self.known_bt_peers[mac] = {
            "address":   mac,
            "node_id":   node_id,
            "caps":      {},
            "last_seen": time.time(),
        }
        print(f"[BT] Static peer added: {node_id[:12]} @ {mac}")

    def _send_rfcomm(self, addr: str, message: dict):
        """Open a short-lived RFCOMM connection and send a message dict."""
        try:
            bt_sock = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM,
            )
            bt_sock.settimeout(5)
            bt_sock.connect((addr, RFCOMM_PORT))
            bt_sock.send(json.dumps(message).encode())
            bt_sock.close()
            print(f"[BT] Sent {message.get('type')} to {addr}")
        except Exception as e:
            print(f"[BT] Send error to {addr}: {e}")

    # ------------------------------------------------------------------
    # RFCOMM inbound (server side)
    # ------------------------------------------------------------------

    def start_rfcomm_server(self):
        """Listen for incoming RFCOMM connections from other EdgeMind nodes."""
        try:
            server = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM,
            )
            # Linux requires an explicit Bluetooth MAC address for bind();
            # "00:00:00:00:00:00" acts as BDADDR_ANY and works on Linux.
            # Windows accepts an empty string, so fall back to that if the
            # zero-MAC bind fails (e.g. on Windows or older kernels).
            try:
                server.bind(("00:00:00:00:00:00", RFCOMM_PORT))
            except Exception:
                try:
                    server.bind(("", RFCOMM_PORT))
                except Exception as e:
                    print(f"[BT] RFCOMM bind failed: {e} — server disabled")
                    return

            server.listen(5)
            print(f"[BT] RFCOMM server listening on port {RFCOMM_PORT}")

            while self.running:
                try:
                    server.settimeout(2)
                    client, addr = server.accept()
                    threading.Thread(
                        target=self._handle_rfcomm_client,
                        args=(client, addr),
                        daemon=True,
                    ).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[BT] RFCOMM accept error: {e}")
                    break
        except Exception as e:
            print(f"[BT] RFCOMM server error: {e}")

    def _handle_rfcomm_client(self, client, addr):
        """Exchange capabilities with an inbound RFCOMM connection."""
        peer_addr = addr[0]  # addr is (mac, channel) tuple from accept()
        try:
            # Receive peer capabilities first (client sends first)
            data     = client.recv(4096)
            peer_cap = json.loads(data.decode())

            peer_id = peer_cap.get("node_id")
            if peer_id and peer_id != self.node_id:
                self.known_bt_peers[addr[0]] = {
                    "address":   addr[0],
                    "node_id":   peer_id,
                    "caps":      peer_cap,
                    "last_seen": time.time(),
                }
                print(f"[BT] Peer registered: {peer_id[:12]} @ {addr[0]}")
                for cb in self._callbacks:
                    cb(json.dumps(peer_cap).encode(), addr[0])

            # Reply with our own capabilities before updating state, so the
            # remote side is never left waiting if an exception fires later.
            cap = get_capabilities()
            cap["node_id"] = self.node_id
            client.send(json.dumps(cap).encode())
        except Exception as e:
            print(f"[BT] Client handler error: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass
