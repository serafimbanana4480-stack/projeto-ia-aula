"""Rate limiter singleton for NEXUS IDE.

Extracted to its own module to avoid circular imports between main.py and route files.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])
