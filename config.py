"""
config.py — Central configuration for EdgeMind.

All hardcoded values live here. Override any setting via environment variable.
"""

import os

# Ollama local LLM
OLLAMA_BASE_URL = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL",  "llama3.2:3b")

# API socket server
API_HOST = os.environ.get("EDGEMIND_API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("EDGEMIND_API_PORT", "9000"))

# Network payload guard — reject messages larger than this before parsing
MAX_PAYLOAD_BYTES = int(os.environ.get("EDGEMIND_MAX_PAYLOAD",
                                       str(4 * 1024 * 1024)))  # 4 MB

# Auto-trigger timing
TRIGGER_INTERVAL = int(os.environ.get("EDGEMIND_TRIGGER_INTERVAL", "5"))
MIN_READINGS     = int(os.environ.get("EDGEMIND_MIN_READINGS",     "3"))

# Security keypair path
NODE_KEYPAIR_PATH = os.environ.get("EDGEMIND_KEYPAIR", ".node_keypair")
