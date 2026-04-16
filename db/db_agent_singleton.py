"""
db/db_agent_singleton.py — Module-level singleton so the entire system
shares one DBAgent instance (and therefore one database connection pool).

Usage:
    from db.db_agent_singleton import get_db, init_db

    db = get_db()               # returns existing agent, creates if needed
    db = init_db(get_peers_fn)  # (re-)create with a known-peers callback
"""

from db.db_agent import DBAgent

_agent: DBAgent = None


def get_db(get_peers_fn=None) -> DBAgent:
    """Return the shared DBAgent, creating it with SQLite on first call."""
    global _agent
    if _agent is None:
        _agent = DBAgent(get_peers_fn=get_peers_fn)
    return _agent


def init_db(get_peers_fn=None) -> DBAgent:
    """(Re-)initialise the shared DBAgent. Call once at startup."""
    global _agent
    _agent = DBAgent(get_peers_fn=get_peers_fn)
    return _agent
