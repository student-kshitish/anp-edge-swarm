"""
anp/protocol.py — Official ANP message schema for EdgeMind swarms.

Any agent written in any language that produces and consumes messages
in this format can join an EdgeMind swarm without modification.
"""

import json
import time
import uuid
from enum import Enum
from typing import Optional

PROTOCOL_VERSION = "1.0.0"
MIN_COMPATIBLE   = "1.0.0"
MAX_COMPATIBLE   = "1.99.99"

# Keep ANP_VERSION as an alias so existing callers don't break.
ANP_VERSION = PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    # Discovery
    ANNOUNCE = "ANNOUNCE"
    PING     = "PING"
    PONG     = "PONG"

    # Task lifecycle
    TASK_ASSIGN = "TASK_ASSIGN"
    TASK_ACCEPT = "TASK_ACCEPT"
    TASK_REJECT = "TASK_REJECT"
    TASK_RESULT = "TASK_RESULT"
    TASK_FAILED = "TASK_FAILED"

    # Agent communication
    SENSOR_READING = "SENSOR_READING"
    ANOMALY_ALERT  = "ANOMALY_ALERT"
    ACTION_REQUEST = "ACTION_REQUEST"
    ACTION_CONFIRM = "ACTION_CONFIRM"

    # System
    HEARTBEAT          = "HEARTBEAT"
    DB_SYNC            = "DB_SYNC"
    INTENT             = "INTENT"
    VERSION_HANDSHAKE  = "VERSION_HANDSHAKE"


class Priority(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def compare_versions(v1: str, v2: str) -> int:
    """Return -1, 0, or 1 as v1 < v2, v1 == v2, or v1 > v2."""
    p1 = [int(x) for x in v1.split(".")]
    p2 = [int(x) for x in v2.split(".")]
    for a, b in zip(p1, p2):
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


def is_compatible_version(version: str) -> bool:
    try:
        if compare_versions(version, MIN_COMPATIBLE) < 0:
            return False
        if compare_versions(version, MAX_COMPATIBLE) > 0:
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_message(
    msg_type:    MessageType,
    payload:     dict,
    sender_id:   str,
    receiver_id: str           = "broadcast",
    priority:    Priority      = Priority.MEDIUM,
    reply_to:    Optional[str] = None,
    task_id:     Optional[str] = None,
) -> dict:
    """Construct a fully-formed ANP envelope."""
    return {
        "anp_version":    PROTOCOL_VERSION,
        "min_compatible": MIN_COMPATIBLE,
        "msg_id":         str(uuid.uuid4()),
        "msg_type":       msg_type.value,
        "sender_id":      sender_id,
        "receiver_id":    receiver_id,
        "timestamp":      time.time(),
        "priority":       priority.value,
        "reply_to":       reply_to,
        "task_id":        task_id or str(uuid.uuid4()),
        "payload":        payload,
        "signature":      None,  # reserved for future auth layer
    }


# ---------------------------------------------------------------------------
# Domain-specific builders
# ---------------------------------------------------------------------------

def build_sensor_reading(
    sender_id:   str,
    sensor_type: str,
    value:       float,
    unit:        str,
    status:      str,
    raw:         dict,
) -> dict:
    return build_message(
        msg_type  = MessageType.SENSOR_READING,
        sender_id = sender_id,
        payload   = {
            "sensor_type": sensor_type,
            "value":       value,
            "unit":        unit,
            "status":      status,
            "raw":         raw,
            "location":    None,
        },
    )


def build_anomaly_alert(
    sender_id:    str,
    anomaly_type: str,
    severity:     Priority,
    field:        str,
    value:        float,
    expected:     float,
    description:  str,
) -> dict:
    return build_message(
        msg_type  = MessageType.ANOMALY_ALERT,
        sender_id = sender_id,
        priority  = severity,
        payload   = {
            "anomaly_type": anomaly_type,
            "field":        field,
            "value":        value,
            "expected":     expected,
            "deviation":    abs(value - expected),
            "description":  description,
            "auto_action":  severity in (Priority.HIGH, Priority.CRITICAL),
        },
    )


def build_task_assign(
    sender_id:   str,
    receiver_id: str,
    task_type:   str,
    sensor_data: dict,
    window:      list,
    brain_ip:    str,
) -> dict:
    return build_message(
        msg_type    = MessageType.TASK_ASSIGN,
        sender_id   = sender_id,
        receiver_id = receiver_id,
        payload     = {
            "task_type":   task_type,
            "sensor_data": sensor_data,
            "window":      window,
            "brain_ip":    brain_ip,
            "timeout_sec": 15,
        },
    )


def build_task_result(
    sender_id:  str,
    task_id:    str,
    task_type:  str,
    result:     dict,
    elapsed_ms: int,
    success:    bool,
) -> dict:
    return build_message(
        msg_type  = MessageType.TASK_RESULT,
        sender_id = sender_id,
        task_id   = task_id,
        payload   = {
            "task_type":  task_type,
            "result":     result,
            "elapsed_ms": elapsed_ms,
            "success":    success,
            "error":      None if success else result.get("error"),
        },
    )


def build_action_request(
    sender_id:   str,
    action_type: str,
    urgency:     Priority,
    description: str,
    data:        dict,
) -> dict:
    return build_message(
        msg_type  = MessageType.ACTION_REQUEST,
        sender_id = sender_id,
        priority  = urgency,
        payload   = {
            "action_type":  action_type,
            "urgency":      urgency.value,
            "description":  description,
            "data":         data,
            "auto_execute": urgency == Priority.CRITICAL,
        },
    )


# ---------------------------------------------------------------------------
# Version handshake builders
# ---------------------------------------------------------------------------

def build_version_handshake(sender_id: str) -> dict:
    return {
        "type":           "VERSION_HANDSHAKE",
        "anp_version":    PROTOCOL_VERSION,
        "min_compatible": MIN_COMPATIBLE,
        "max_compatible": MAX_COMPATIBLE,
        "sender_id":      sender_id,
        "timestamp":      time.time(),
    }


def validate_peer_version(peer_msg: dict) -> dict:
    peer_version = peer_msg.get("anp_version", "")
    peer_min     = peer_msg.get("min_compatible", "")

    if not peer_version:
        return {"compatible": False, "reason": "missing version"}

    if peer_min and compare_versions(PROTOCOL_VERSION, peer_min) < 0:
        return {
            "compatible": False,
            "reason": f"our version {PROTOCOL_VERSION} too old for peer",
        }

    if not is_compatible_version(peer_version):
        return {
            "compatible": False,
            "reason": f"peer version {peer_version} incompatible",
        }

    return {
        "compatible":   True,
        "peer_version": peer_version,
        "our_version":  PROTOCOL_VERSION,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = frozenset(
    ["anp_version", "msg_id", "msg_type", "sender_id", "timestamp", "payload"]
)


def validate_message(msg: dict) -> tuple[bool, str]:
    """
    Validate an ANP message envelope.

    Returns (True, "OK") on success or (False, reason) on failure.
    """
    for field in _REQUIRED_FIELDS:
        if field not in msg:
            return False, f"Missing required field: {field}"

    version = msg.get("anp_version", "")
    if not is_compatible_version(version):
        return False, f"Incompatible version: {version}"

    try:
        MessageType(msg["msg_type"])
    except ValueError:
        return False, f"Unknown msg_type: {msg['msg_type']}"

    return True, "OK"


# ---------------------------------------------------------------------------
# Wire encoding
# ---------------------------------------------------------------------------

def serialize(msg: dict) -> bytes:
    """Encode an ANP message to compact JSON bytes for transmission."""
    return json.dumps(msg, separators=(",", ":")).encode()


def deserialize(data: bytes) -> dict:
    """Decode received bytes back into an ANP message dict."""
    return json.loads(data.decode())
