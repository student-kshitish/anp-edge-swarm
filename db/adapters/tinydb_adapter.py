"""
db/adapters/tinydb_adapter.py — TinyDB adapter for small / Android Termux nodes.
Install: pip install tinydb
Falls back gracefully — DBAgent tries this only if tinydb is importable.
"""

import json
import uuid
from datetime import datetime, timezone

from db.adapters.base import BaseDBAdapter


class TinyDBAdapter(BaseDBAdapter):

    def __init__(self, db_path: str = "edgemind_tiny.json"):
        self.db_path  = db_path
        self._db      = None
        self._tables  = {}

    def get_type(self) -> str:
        return "tinydb"

    def init(self) -> None:
        from tinydb import TinyDB
        self._db = TinyDB(self.db_path)
        print(f"[DB] TinyDB initialized: {self.db_path}")

    def _table(self, name: str):
        if name not in self._tables:
            self._tables[name] = self._db.table(name)
        return self._tables[name]

    def save(self, table: str, record: dict) -> str:
        from tinydb import Query
        record    = dict(record)
        record_id = record.get("record_id", str(uuid.uuid4()))
        record["record_id"] = record_id
        record.setdefault(
            "timestamp",
            datetime.now(timezone.utc).isoformat(),
        )
        Q = Query()
        t = self._table(table)
        if t.search(Q.record_id == record_id):
            t.update(record, Q.record_id == record_id)
        else:
            t.insert(record)
        return record_id

    def fetch(self, table: str, filters: dict = None,
              limit: int = 100) -> list:
        t       = self._table(table)
        results = t.all()
        if filters:
            for k, v in filters.items():
                results = [r for r in results if r.get(k) == v]
        results.sort(
            key=lambda x: x.get("timestamp", ""),
            reverse=True,
        )
        return results[:limit]

    def update(self, table: str, record_id: str,
               data: dict) -> bool:
        from tinydb import Query
        Q = Query()
        self._table(table).update(data, Q.record_id == record_id)
        return True

    def delete(self, table: str, record_id: str) -> bool:
        from tinydb import Query
        Q = Query()
        self._table(table).remove(Q.record_id == record_id)
        return True

    def count(self, table: str) -> int:
        return len(self._table(table).all())
