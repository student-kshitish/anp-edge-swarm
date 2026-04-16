"""
examples/run_db_status.py — Show database status for the local node.
Run from project root: python examples/run_db_status.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath("."))

from db.db_agent_singleton import init_db

db = init_db()

print("=" * 50)
print("  EdgeMind DB Agent Status")
print("=" * 50)

status = db.status()
print(f"\nLocal node:")
for k, v in status.items():
    print(f"  {k}: {v}")

print(f"\nRecent sensor readings:")
for r in db.get_recent_readings(limit=5):
    print(
        f"  {r.get('timestamp', '')[:19]} "
        f"{r.get('sensor_type', '?'):12} "
        f"node={r.get('node_id', '?')[:8]}"
    )

print(f"\nWork orders:")
for wo in db.fetch("work_orders", limit=5):
    print(
        f"  {wo.get('record_id', '?')[:12]} "
        f"[{wo.get('priority', '?')}] "
        f"{wo.get('description', '')[:40]}"
    )

print(f"\nPredictions:")
for p in db.fetch("predictions", limit=3):
    print(
        f"  {p.get('timestamp', '')[:19]} "
        f"status={p.get('status', '?')} "
        f"urgency={p.get('urgency', '?')}"
    )
