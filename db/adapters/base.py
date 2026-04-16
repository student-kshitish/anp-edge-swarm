"""
db/adapters/base.py — Abstract interface that every database adapter must implement.
All adapters are drop-in replaceable: SQLite, TinyDB, PostgreSQL, JSON files.
"""

from abc import ABC, abstractmethod


class BaseDBAdapter(ABC):

    @abstractmethod
    def init(self) -> None:
        """Create tables / collections / directories as needed."""
        pass

    @abstractmethod
    def save(self, table: str, record: dict) -> str:
        """Upsert record into table. Returns the record_id."""
        pass

    @abstractmethod
    def fetch(self, table: str, filters: dict = None,
              limit: int = 100) -> list:
        """Return up to limit records, newest first. filters is AND-combined."""
        pass

    @abstractmethod
    def update(self, table: str, record_id: str,
               data: dict) -> bool:
        """Patch an existing record by record_id."""
        pass

    @abstractmethod
    def delete(self, table: str, record_id: str) -> bool:
        """Remove a record by record_id."""
        pass

    @abstractmethod
    def count(self, table: str) -> int:
        """Return total row count for the table."""
        pass

    @abstractmethod
    def get_type(self) -> str:
        """Return a short identifier: 'sqlite', 'tinydb', 'postgres', 'json'."""
        pass

    def health_check(self) -> bool:
        """Return True if the adapter can serve queries."""
        try:
            self.count("sensor_readings")
            return True
        except Exception:
            return False
