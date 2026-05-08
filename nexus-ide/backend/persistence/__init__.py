"""Persistence layer for NEXUS IDE — SQLite-backed storage for projects, sessions, messages, decisions."""
from backend.persistence.db import get_db, init_db

__all__ = ["get_db", "init_db"]
