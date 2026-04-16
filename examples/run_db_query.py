"""
examples/run_db_query.py — CLI tool to query the distributed SQLite database.
Run from the project root: python examples/run_db_query.py
"""

import sys
import os

sys.path.insert(0, os.path.abspath("."))

from db.schema import init_db
from db.query import (
    get_recent_readings,
    get_work_orders,
    get_predictions,
    get_stats,
    get_peer_list,
)

init_db()

print("=" * 50)
print("  EdgeMind Database Query Tool")
print("=" * 50)

stats = get_stats()
print(f"\nDatabase Stats:")
for k, v in stats.items():
    print(f"  {k}: {v}")

print(f"\nLast 5 sensor readings:")
for r in get_recent_readings(limit=5):
    print(f"  {r['timestamp'][:19]} {r['sensor_type']:12} "
          f"{r['value_num']} {r['value_text'] or ''}")

print(f"\nOpen work orders:")
for wo in get_work_orders(status="OPEN"):
    print(f"  {wo['wo_id']} [{wo['priority']}] {wo['description'][:50]}")

print(f"\nKnown peers:")
for p in get_peer_list():
    print(f"  {p['node_id'][:12]} @ {p['ip']} ({p['transport']})")
