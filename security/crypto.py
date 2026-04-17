"""
security/crypto.py — Zero-trust node security via HMAC-SHA256 mutual auth.

Every node generates a permanent 256-bit secret key on first launch.
Peers authenticate using a challenge/response protocol: the challenger
sends a random nonce, the responder proves knowledge of their shared secret
by computing HMAC-SHA256(secret, nonce + peer_id). Rogue nodes that fail
verification are blacklisted for the lifetime of the process.

All message signing uses the same HMAC-SHA256 primitive so every TCP packet
can be integrity-checked without external crypto dependencies.
"""

import hashlib
import hmac
import json
import os
import secrets
import time

from swarm.node_identity import get_node_id

KEY_FILE = ".node_keypair"


class NodeSecurity:
    """HMAC-SHA256 identity and challenge/response authentication for swarm nodes."""

    def __init__(self):
        self.node_id    = get_node_id()
        self.secret_key = self._load_or_generate_key()
        self.trusted    = {}    # node_id → shared_secret (bytes)
        self.blacklist  = set() # node_ids permanently rejected
        self.challenges = {}    # node_id → {nonce, created_at, answered}
        print(f"[SECURITY] Node key loaded: {self.node_id[:12]}")

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _load_or_generate_key(self) -> bytes:
        if os.path.exists(KEY_FILE):
            try:
                with open(KEY_FILE, "rb") as f:
                    key = f.read()
                if len(key) == 32:
                    return key
            except OSError:
                pass
        key = secrets.token_bytes(32)
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        print("[SECURITY] New keypair generated")
        return key

    # ------------------------------------------------------------------
    # Message signing and verification
    # ------------------------------------------------------------------

    def sign_message(self, msg: dict) -> dict:
        """
        Sign *msg* in-place and return it.

        The signature covers every field except `signature` itself,
        serialised with sorted keys for determinism.
        """
        msg_copy = dict(msg)
        msg_copy.pop("signature", None)
        msg_copy.pop("signed_by",  None)
        payload = json.dumps(msg_copy, sort_keys=True).encode()
        sig = hmac.new(
            self.secret_key, payload, hashlib.sha256
        ).hexdigest()
        msg["signature"] = sig
        msg["signed_by"]  = self.node_id
        return msg

    def verify_signature(self, msg: dict, peer_secret: bytes) -> bool:
        """
        Verify that *msg* was signed by a node holding *peer_secret*.

        Mutates msg temporarily to extract the signature fields, then
        restores them. Uses constant-time comparison to prevent timing attacks.
        """
        sig       = msg.pop("signature", None)
        signed_by = msg.pop("signed_by",  None)
        if not sig or not signed_by:
            return False
        payload  = json.dumps(msg, sort_keys=True).encode()
        expected = hmac.new(peer_secret, payload, hashlib.sha256).hexdigest()
        # Restore fields before returning so the caller's dict is unchanged
        msg["signature"] = sig
        msg["signed_by"]  = signed_by
        return hmac.compare_digest(sig, expected)

    # ------------------------------------------------------------------
    # Challenge / response
    # ------------------------------------------------------------------

    def create_challenge(self, peer_id: str) -> dict:
        """Generate and store a fresh challenge for *peer_id*."""
        nonce = secrets.token_hex(16)
        self.challenges[peer_id] = {
            "nonce":      nonce,
            "created_at": time.time(),
            "answered":   False,
        }
        return {
            "type":      "AUTH_CHALLENGE",
            "sender_id": self.node_id,
            "peer_id":   peer_id,
            "nonce":     nonce,
            "timestamp": time.time(),
        }

    def answer_challenge(self, challenge: dict) -> dict:
        """Compute a proof-of-identity response to an incoming challenge."""
        nonce = challenge.get("nonce", "")
        proof = hmac.new(
            self.secret_key,
            f"{nonce}{self.node_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "type":      "AUTH_RESPONSE",
            "sender_id": self.node_id,
            "nonce":     nonce,
            "proof":     proof,
            "timestamp": time.time(),
        }

    def verify_challenge_response(
        self, response: dict, peer_secret: bytes
    ) -> bool:
        """
        Validate a peer's AUTH_RESPONSE.

        Looks up the pending challenge by nonce rather than peer_id because
        at challenge-creation time only the peer's IP is known, not its node_id.
        The response carries the peer's real node_id as `sender_id`.

        On success the peer is added to `trusted`. On failure the peer is
        added to `blacklist` and all future messages from it should be dropped.
        """
        peer_id = response.get("sender_id", "")
        nonce   = response.get("nonce",     "")
        proof   = response.get("proof",     "")

        # Find challenge entry by nonce (the only value both sides know up-front)
        challenge_entry = None
        challenge_key   = None
        for key, entry in self.challenges.items():
            if entry["nonce"] == nonce:
                challenge_entry = entry
                challenge_key   = key
                break

        if challenge_entry is None:
            return False

        expected = hmac.new(
            peer_secret,
            f"{nonce}{peer_id}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(proof, expected):
            challenge_entry["answered"] = True
            # Re-key to actual node_id so future lookups work by node_id
            if challenge_key != peer_id:
                self.challenges[peer_id] = self.challenges.pop(challenge_key)
            self.trusted[peer_id] = peer_secret
            print(f"[SECURITY] Peer authenticated: {peer_id[:12]}")
            return True

        self.blacklist.add(peer_id)
        print(f"[SECURITY] !! ROGUE NODE rejected: {peer_id[:12]}")
        return False

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    def is_trusted(self, node_id: str) -> bool:
        return node_id in self.trusted

    def is_blacklisted(self, node_id: str) -> bool:
        return node_id in self.blacklist

    def get_status(self) -> dict:
        return {
            "node_id":     self.node_id[:12],
            "trusted":     len(self.trusted),
            "blacklisted": len(self.blacklist),
            "challenges":  len(self.challenges),
        }
