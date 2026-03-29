"""
swarm/nat_traversal.py — UDP hole punching for NAT traversal.

Usage:
    from swarm.nat_traversal import punch_hole
    sock, addr = punch_hole("1.2.3.4", 6883)
    if sock:
        # hole is open, use sock for data exchange
"""

import socket
import time


def punch_hole(
    peer_public_ip: str,
    peer_public_port: int,
    local_port: int = 6883,
):
    """
    Attempt UDP hole punching to reach peer_public_ip:peer_public_port.

    Steps:
      1. Bind a UDP socket to local_port.
      2. Send b'HOLE_PUNCH' to the peer 10 times (0.1 s apart) to open the NAT mapping.
      3. Wait up to 5 s for b'HOLE_PUNCH' back from the peer.

    Returns:
      (socket, addr)  if the hole was punched successfully.
      (None, None)    on timeout or error.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", local_port))
    except OSError as e:
        print(f"[NAT] Cannot bind port {local_port}: {e}", flush=True)
        return None, None

    peer_addr = (peer_public_ip, peer_public_port)

    # Send 10 punches to open outbound NAT mapping
    for _ in range(10):
        try:
            sock.sendto(b"HOLE_PUNCH", peer_addr)
        except Exception as e:
            print(f"[NAT] Send error: {e}", flush=True)
        time.sleep(0.1)

    # Wait up to 5 s for the peer's return punch
    sock.settimeout(5.0)
    try:
        data, addr = sock.recvfrom(64)
        if data == b"HOLE_PUNCH":
            print(f"[NAT] Hole punched with {addr}", flush=True)
            sock.settimeout(None)
            return sock, addr
    except socket.timeout:
        pass
    except Exception as e:
        print(f"[NAT] Receive error: {e}", flush=True)

    print(f"[NAT] Hole punch failed with {peer_public_ip}:{peer_public_port}", flush=True)
    sock.close()
    return None, None
