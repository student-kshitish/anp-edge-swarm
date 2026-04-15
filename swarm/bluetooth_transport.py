"""
swarm/bluetooth_transport.py — BLE advertising and scanning via bleak.

Scans for nearby EDGEMIND nodes every 10 seconds and connects via GATT
to exchange structured JSON messages.  If bleak is not installed the
transport silently degrades: start() returns False and nothing breaks.
"""

import asyncio
import json
import threading
import time

from swarm.node_identity import get_node_id
from swarm.capability import get_capabilities

SERVICE_UUID = "12345678-1234-5678-1234-567812345678"
CHAR_UUID    = "12345678-1234-5678-1234-567812345679"


class BluetoothTransport:

    def __init__(self):
        self.node_id        = get_node_id()
        self.known_bt_peers = {}   # BLE address -> peer info dict
        self.running        = False
        self._callbacks     = []
        self._loop          = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, on_message=None) -> bool:
        """Start BLE scanning in a background thread.

        Returns True if bleak is available and scanning has begun,
        False if bleak is missing (graceful fallback).
        """
        try:
            import bleak  # noqa: F401 — presence check only
        except ImportError:
            print("[BT] bleak not installed — pip install bleak")
            return False

        if on_message:
            self._callbacks.append(on_message)

        self._loop   = asyncio.new_event_loop()
        self.running = True

        t = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="bt-transport",
        )
        t.start()
        print("[BT] Bluetooth transport started")
        return True

    def send_message(self, message: dict):
        """Fire-and-forget broadcast to every known BLE peer."""
        if not self._loop:
            return
        for addr in list(self.known_bt_peers.keys()):
            asyncio.run_coroutine_threadsafe(
                self.send_to_peer(addr, message),
                self._loop,
            )

    def get_known_peers(self) -> dict:
        return dict(self.known_bt_peers)

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # Internal event-loop helpers
    # ------------------------------------------------------------------

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        await asyncio.gather(
            self._scan_loop(),
        )

    async def _scan_loop(self):
        from bleak import BleakScanner
        while self.running:
            try:
                devices = await BleakScanner.discover(timeout=5.0)
                for device in devices:
                    if "EDGEMIND" in (device.name or ""):
                        if device.address not in self.known_bt_peers:
                            self.known_bt_peers[device.address] = {
                                "address":   device.address,
                                "name":      device.name,
                                "rssi":      device.rssi,
                                "last_seen": time.time(),
                            }
                            print(f"[BT] Found peer: {device.name} ({device.address})")
            except Exception as e:
                print(f"[BT] Scan error: {e}")
            await asyncio.sleep(10)

    async def send_to_peer(self, address: str, message: dict) -> bool:
        from bleak import BleakClient
        try:
            async with BleakClient(address, timeout=10) as client:
                data = json.dumps(message).encode()
                await client.write_gatt_char(CHAR_UUID, data)
                print(f"[BT] Sent {message.get('type')} to {address}")
                return True
        except Exception as e:
            print(f"[BT] Send error to {address}: {e}")
            return False
