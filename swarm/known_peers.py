"""
swarm/known_peers.py — Static list of known peer IPs for this deployment.

Edit this file to match your actual machine IPs.
Used by peer_client.py to establish the initial TCP capability exchange.

IP selection guide:
  # For same-network: use 192.168.x.x IPs
  # For cross-network: use Tailscale 100.x.x.x IPs
  # For internet: leave empty and use --bootstrap flag only
"""

PEER_IPS = [
    "192.168.1.11",   # Windows laptop
    "192.168.1.40",  # Victus Linux
]
