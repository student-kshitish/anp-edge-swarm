"""
examples/run_bootstrap.py — Run a DHT bootstrap node.

Anyone can run this to become a bootstrap entry point for the swarm.
Other nodes pass this machine's IP with --bootstrap <ip> when starting.

Usage:
    python examples/run_bootstrap.py

Share the printed IP with other nodes so they can join the same DHT.
"""

import sys
import os

# Allow running from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swarm.bootstrap_server import run
import asyncio

if __name__ == "__main__":
    asyncio.run(run())
