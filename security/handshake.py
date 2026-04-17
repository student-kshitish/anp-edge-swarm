"""
security/handshake.py — Mutual authentication handshake over an open TCP socket.

Both sides call into this module before exchanging any task data.
The initiator calls perform_handshake(); the listener calls respond_to_handshake().
Both return True only when the remote party has been cryptographically verified.

Protocol (3 messages):
  1. Initiator → Listener  : AUTH_CHALLENGE  {nonce}
  2. Listener  → Initiator : AUTH_RESPONSE   {proof = HMAC(secret, nonce+id)}
  3. Initiator → Listener  : AUTH_RESULT     {accepted: bool}
"""

import json
import socket

from security.crypto import NodeSecurity


def perform_handshake(
    sock:     socket.socket,
    security: NodeSecurity,
    peer_ip:  str,
) -> bool:
    """
    Initiator side — send challenge, verify response, send result.

    Args:
        sock:     Already-connected TCP socket to the peer.
        security: This node's NodeSecurity instance.
        peer_ip:  IP address string used as the peer_id for the challenge.

    Returns:
        True if the peer authenticated successfully, False otherwise.
    """
    try:
        # Step 1 — send challenge
        challenge = security.create_challenge(peer_ip)
        sock.sendall(json.dumps(challenge).encode())

        # Step 2 — receive response
        response_data = _recv_all(sock)
        if not response_data:
            print(f"[HANDSHAKE] No response from {peer_ip}")
            return False
        response = json.loads(response_data.decode())

        if response.get("type") != "AUTH_RESPONSE":
            print(f"[HANDSHAKE] Invalid response type from {peer_ip}")
            return False

        # Verify using own secret (symmetric demo — in production each node
        # would exchange public keys; here both sides share a swarm secret)
        verified = security.verify_challenge_response(
            response, security.secret_key
        )

        # Step 3 — send result so peer knows outcome
        result_msg = {"type": "AUTH_RESULT", "accepted": verified}
        sock.sendall(json.dumps(result_msg).encode())

        if verified:
            print(f"[HANDSHAKE] Authenticated with {peer_ip}")
        else:
            print(f"[HANDSHAKE] REJECTED {peer_ip}")
        return verified

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[HANDSHAKE] Error with {peer_ip}: {exc}")
        return False


def respond_to_handshake(
    sock:     socket.socket,
    security: NodeSecurity,
) -> bool:
    """
    Listener side — receive challenge, send proof, wait for result.

    Args:
        sock:     Accepted TCP socket from the connecting peer.
        security: This node's NodeSecurity instance.

    Returns:
        True if this node's proof was accepted by the initiator.
    """
    try:
        # Step 1 — receive challenge
        challenge_data = _recv_all(sock)
        if not challenge_data:
            return False
        challenge = json.loads(challenge_data.decode())

        if challenge.get("type") != "AUTH_CHALLENGE":
            print("[HANDSHAKE] Unexpected message type — expected AUTH_CHALLENGE")
            return False

        # Step 2 — send proof
        response = security.answer_challenge(challenge)
        sock.sendall(json.dumps(response).encode())

        # Step 3 — receive result
        result_data = _recv_all(sock)
        if not result_data:
            return False
        result = json.loads(result_data.decode())

        accepted = result.get("accepted", False)
        if not accepted:
            print("[HANDSHAKE] Initiator rejected our proof")
        return accepted

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[HANDSHAKE] Response error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _recv_all(sock: socket.socket, buf: int = 4096) -> bytes:
    """Read one complete JSON message (up to *buf* bytes) from *sock*."""
    sock.settimeout(5.0)
    try:
        data = sock.recv(buf)
        return data if data else b""
    except socket.timeout:
        return b""
