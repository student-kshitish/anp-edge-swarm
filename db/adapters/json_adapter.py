"""
db/adapters/json_adapter.py — JSON file adapter. Ultimate fallback.
Works on absolutely any device with Python. Zero dependencies.
One JSON file per table inside a data directory.
"""

import json
import uuid
import os
import threading
from datetime import datetime, timezone

from db.adapters.base import BaseDBAdapter


class JSONAdapter(BaseDBAdapter):

    def __init__(self, data_dir: str = "edgemind_data"):
        self.data_dir = data_dir
        self._lock    = threading.Lock()

    def get_type(self) -> str:
        return "json"

    def init(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        print(f"[DB] JSON adapter initialized: {self.data_dir}")

    def _path(self, table: str) -> str:
        return os.path.join(self.data_dir, f"{table}.json")

    def _load(self, table: str) -> list:
        path = self._path(table)
        if not os.path.exists(path):
            return []
        with open(path, "r") as f:
            return json.load(f)

    def _dump(self, table: str, data: list) -> None:
        with open(self._path(table), "w") as f:
            json.dump(data, f, indent=2)

    def save(self, table: str, record: dict) -> str:
        record    = dict(record)
        record_id = record.get("record_id", str(uuid.uuid4()))
        record["record_id"] = record_id
        record.setdefault(
            "timestamp",
            datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            data = self._load(table)
            # Remove old version if present (upsert behaviour)
            data = [r for r in data if r.get("record_id") != record_id]
            data.append(record)
            self._dump(table, data)
        return record_id

    def fetch(self, table: str, filters: dict = None,
              limit: int = 100) -> list:
        with self._lock:
            data = self._load(table)
        if filters:
            for k, v in filters.items():
                data = [r for r in data if r.get(k) == v]
        data.sort(
            key=lambda x: x.get("timestamp", ""),
            reverse=True,
        )
        return data[:limit]

    def update(self, table: str, record_id: str,
               data: dict) -> bool:
        with self._lock:
            records = self._load(table)
            for r in records:
                if r.get("record_id") == record_id:
                    r.update(data)
            self._dump(table, records)
        return True

    def delete(self, table: str, record_id: str) -> bool:
        with self._lock:
            records = self._load(table)
            records = [r for r in records
                       if r.get("record_id") != record_id]
            self._dump(table, records)
        return True

    def count(self, table: str) -> int:
        # Bypass the limit cap in fetch for an accurate total
        with self._lock:
            return len(self._load(table))
