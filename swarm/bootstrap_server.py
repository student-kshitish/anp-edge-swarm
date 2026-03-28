"""
swarm/bootstrap_server.py — Standalone Kademlia DHT bootstrap node.

Run this on any machine with a public / reachable IP to create a
private bootstrap point for your swarm.  Other nodes pass this
machine's IP via --bootstrap <ip> when starting.

Usage:
    python swarm/bootstrap_server.py
    python examples/run_bootstrap.py   # convenience wrapper
"""

import asyncio
import socket


async def run():
    from kademlia.network import Server

    server = Server()
    await server.listen(6881)

    ip = socket.gethostbyname(socket.gethostname())
    print("[BOOTSTRAP] DHT bootstrap server running on port 6881", flush=True)
    print("[BOOTSTRAP] Share your IP with other nodes to connect", flush=True)
    print(f"[BOOTSTRAP] Your IP: {ip}", flush=True)
    print(f"[BOOTSTRAP] Other nodes join with: --bootstrap {ip}", flush=True)

    try:
        await asyncio.sleep(float("inf"))
    except (KeyboardInterrupt, asyncio.CancelledError):
        server.stop()
        print("[BOOTSTRAP] Shutting down.", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
