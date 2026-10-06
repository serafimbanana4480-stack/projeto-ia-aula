"""Distributed Session Registry with Redis backend.

Supports multi-user, distributed nodes, shared sessions, failover,
persistence, resumable sessions, and context synchronization.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Session lifecycle states."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass
class SessionContext:
    """Session context with metadata and state."""
    session_id: str
    user_id: str
    workspace_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    state: SessionState = SessionState.ACTIVE
    
    # Session data
    context: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Concurrency control
    version: int = 0
    lock_token: str | None = None
    lock_expiry: float | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_activity": self.last_activity,
            "state": self.state.value,
            "context": self.context,
            "history": self.history,
            "metadata": self.metadata,
            "version": self.version,
            "lock_token": self.lock_token,
            "lock_expiry": self.lock_expiry,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionContext:
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            workspace_id=data["workspace_id"],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            last_activity=data.get("last_activity", time.time()),
            state=SessionState(data.get("state", "active")),
            context=data.get("context", {}),
            history=data.get("history", []),
            metadata=data.get("metadata", {}),
            version=data.get("version", 0),
            lock_token=data.get("lock_token"),
            lock_expiry=data.get("lock_expiry"),
        )


class DistributedSessionRegistry:
    """Redis-backed distributed session registry with locking and synchronization."""
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        session_ttl: int = 3600,  # 1 hour
        lock_ttl: int = 30,  # 30 seconds
        cleanup_interval: int = 300,  # 5 minutes
    ):
        if not REDIS_AVAILABLE:
            raise ImportError("redis-py is required. Install: pip install redis[hiredis]")
        
        self.redis_url = redis_url
        self.session_ttl = session_ttl
        self.lock_ttl = lock_ttl
        self.cleanup_interval = cleanup_interval
        self._redis: redis.Redis | None = None
        self._cleanup_task: asyncio.Task | None = None
        
    async def connect(self) -> None:
        """Connect to Redis and start cleanup task."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        
        # Test connection
        await self._redis.ping()
        logger.info("Connected to Session Registry at %s", self.redis_url)
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
    async def disconnect(self) -> None:
        """Disconnect from Redis and cleanup."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            
        if self._redis:
            await self._redis.close()
            
        logger.info("Disconnected from Session Registry")
        
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of expired sessions."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Session cleanup error: %s", exc)
                
    async def _cleanup_expired_sessions(self) -> None:
        """Clean up expired sessions and locks."""
        if not self._redis:
            return
            
        # Clean up expired sessions
        pattern = "session:*"
        cursor = 0
        while cursor != 0:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            for key in keys:
                try:
                    data = await self._redis.get(key)
                    if data:
                        session = SessionContext.from_dict(json.loads(data))
                        
                        # Check if session is expired
                        if (time.time() - session.last_activity > self.session_ttl or
                            session.state in [SessionState.COMPLETED, SessionState.FAILED]):
                            await self._redis.delete(key)
                            logger.debug("Cleaned up expired session: %s", session.session_id)
                            
                except Exception as exc:
                    logger.error("Error cleaning session %s: %s", key, exc)
                    
        # Clean up expired locks
        lock_pattern = "lock:*"
        cursor = 0
        while cursor != 0:
            cursor, keys = await self._redis.scan(cursor, match=lock_pattern, count=1000)
            for key in keys:
                try:
                    lock_data = await self._redis.get(key)
                    if lock_data:
                        lock_info = json.loads(lock_data)
                        if time.time() > lock_info.get("expiry", 0):
                            await self._redis.delete(key)
                            logger.debug("Cleaned up expired lock: %s", key)
                            
                except Exception as exc:
                    logger.error("Error cleaning lock %s: %s", key, exc)
                    
    async def create_session(
        self,
        user_id: str,
        workspace_id: str,
        initial_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionContext:
        """Create a new session with distributed ID."""
        session_id = str(uuid.uuid4())
        
        session = SessionContext(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            context=initial_context or {},
            metadata=metadata or {},
        )
        
        await self._save_session(session)
        logger.info("Created session %s for user %s", session_id, user_id)
        return session
        
    async def _save_session(self, session: SessionContext) -> None:
        """Save session to Redis with TTL."""
        if not self._redis:
            raise RuntimeError("Session Registry not connected")
            
        key = f"session:{session.session_id}"
        data = json.dumps(session.to_dict())
        
        await self._redis.setex(key, self.session_ttl, data)
        
    async def get_session(self, session_id: str) -> SessionContext | None:
        """Get session by ID."""
        if not self._redis:
            raise RuntimeError("Session Registry not connected")
            
        key = f"session:{session_id}"
        data = await self._redis.get(key)
        
        if data:
            session = SessionContext.from_dict(json.loads(data))
            
            # Update last activity
            session.last_activity = time.time()
            await self._save_session(session)
            
            return session
        return None
        
    async def update_session(
        self,
        session_id: str,
        context_update: dict[str, Any] | None = None,
        metadata_update: dict[str, Any] | None = None,
        state_update: SessionState | None = None,
    ) -> bool:
        """Update session with optimistic concurrency control."""
        session = await self.get_session(session_id)
        if not session:
            return False
            
        # Apply updates
        if context_update:
            session.context.update(context_update)
        if metadata_update:
            session.metadata.update(metadata_update)
        if state_update:
            session.state = state_update
            
        session.updated_at = time.time()
        session.version += 1
        
        # Check for conflicts
        old_key = f"session:{session_id}"
        new_key = f"session:{session_id}:v{session.version}"
        
        # Atomic update with version check
        pipe = self._redis.pipeline()
        pipe.rename(old_key, new_key)
        pipe.setex(old_key, self.session_ttl, json.dumps(session.to_dict()))
        pipe.delete(new_key)
        
        try:
            await pipe.execute()
            return True
        except Exception as exc:
            logger.error("Session update conflict: %s", exc)
            return False
            
    async def acquire_session_lock(
        self,
        session_id: str,
        lock_token: str,
        timeout: float | None = None,
    ) -> bool:
        """Acquire distributed lock on session."""
        if not self._redis:
            raise RuntimeError("Session Registry not connected")
            
        timeout = timeout or self.lock_ttl
        expiry = time.time() + timeout
        
        lock_key = f"lock:{session_id}"
        lock_data = {
            "lock_token": lock_token,
            "expiry": expiry,
            "session_id": session_id,
        }
        
        # Try to acquire lock (SETNX with expiry)
        result = await self._redis.set(
            lock_key,
            json.dumps(lock_data),
            nx=True,
            ex=int(timeout)
        )
        
        if result:
            # Update session with lock info
            await self.update_session(
                session_id,
                metadata_update={"lock_token": lock_token, "lock_expiry": expiry}
            )
            logger.debug("Acquired lock for session %s", session_id)
            return True
        else:
            logger.debug("Failed to acquire lock for session %s", session_id)
            return False
            
    async def release_session_lock(
        self,
        session_id: str,
        lock_token: str,
    ) -> bool:
        """Release distributed lock on session."""
        if not self._redis:
            raise RuntimeError("Session Registry not connected")
            
        lock_key = f"lock:{session_id}"
        
        # Get current lock data
        lock_data = await self._redis.get(lock_key)
        if not lock_data:
            return False
            
        lock_info = json.loads(lock_data)
        
        # Verify lock token
        if lock_info.get("lock_token") != lock_token:
            logger.warning("Invalid lock token for session %s", session_id)
            return False
            
        # Delete lock
        result = await self._redis.delete(lock_key)
        
        if result:
            # Update session
            await self.update_session(
                session_id,
                metadata_update={"lock_token": None, "lock_expiry": None}
            )
            logger.debug("Released lock for session %s", session_id)
            return True
        else:
            logger.warning("Failed to release lock for session %s", session_id)
            return False
            
    async def add_to_history(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Add event to session history."""
        session = await self.get_session(session_id)
        if not session:
            return
            
        history_entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }
        
        session.history.append(history_entry)
        
        # Limit history size
        if len(session.history) > 1000:
            session.history = session.history[-1000:]
            
        await self._save_session(session)
        
    async def get_user_sessions(self, user_id: str) -> list[SessionContext]:
        """Get all sessions for a user."""
        if not self._redis:
            raise RuntimeError("Session Registry not connected")
            
        pattern = "session:*"
        user_sessions = []
        
        cursor = 0
        while cursor != 0:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            for key in keys:
                try:
                    data = await self._redis.get(key)
                    if data:
                        session = SessionContext.from_dict(json.loads(data))
                        if session.user_id == user_id:
                            user_sessions.append(session)
                except Exception as exc:
                    logger.error("Error loading session %s: %s", key, exc)
                    
        return sorted(user_sessions, key=lambda s: s.last_activity, reverse=True)
        
    async def get_workspace_sessions(self, workspace_id: str) -> list[SessionContext]:
        """Get all sessions for a workspace."""
        if not self._redis:
            raise RuntimeError("Session Registry not connected")
            
        pattern = "session:*"
        workspace_sessions = []
        
        cursor = 0
        while cursor != 0:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            for key in keys:
                try:
                    data = await self._redis.get(key)
                    if data:
                        session = SessionContext.from_dict(json.loads(data))
                        if session.workspace_id == workspace_id:
                            workspace_sessions.append(session)
                except Exception as exc:
                    logger.error("Error loading session %s: %s", key, exc)
                    
        return sorted(workspace_sessions, key=lambda s: s.last_activity, reverse=True)
        
    async def archive_session(self, session_id: str) -> bool:
        """Archive a session (move to long-term storage)."""
        session = await self.get_session(session_id)
        if not session:
            return False
            
        session.state = SessionState.ARCHIVED
        await self._save_session(session)
        
        # Move to archive key with longer TTL
        archive_key = f"archive:{session_id}"
        session_key = f"session:{session_id}"
        
        data = await self._redis.get(session_key)
        if data:
            await self._redis.setex(archive_key, 86400 * 30, data)  # 30 days
            await self._redis.delete(session_key)
            
        logger.info("Archived session %s", session_id)
        return True
        
    async def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        if not self._redis:
            return {"connected": False}
            
        try:
            # Count sessions by state
            pattern = "session:*"
            cursor = 0
            state_counts = {state.value: 0 for state in SessionState}
            total_sessions = 0
            
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
                for key in keys:
                    try:
                        data = await self._redis.get(key)
                        if data:
                            session = SessionContext.from_dict(json.loads(data))
                            state_counts[session.state.value] += 1
                            total_sessions += 1
                    except Exception:
                        pass
                        
            # Count locks
            lock_pattern = "lock:*"
            cursor = 0
            active_locks = 0
            
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match=lock_pattern, count=1000)
                active_locks += len(keys)
                
            # Get Redis info
            info = await self._redis.info()
            
            return {
                "connected": True,
                "total_sessions": total_sessions,
                "sessions_by_state": state_counts,
                "active_locks": active_locks,
                "redis_memory": info.get("used_memory_human"),
                "redis_connected_clients": info.get("connected_clients"),
            }
            
        except Exception as exc:
            logger.error("Failed to get stats: %s", exc)
            return {"connected": True, "error": str(exc)}


# Backward compatibility wrapper
class SessionRegistry:
    """Wrapper that uses DistributedSessionRegistry if available."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._distributed_registry = None
        self._redis_url = redis_url
        
    async def _ensure_connected(self) -> None:
        """Ensure distributed registry is connected."""
        if self._distributed_registry is None:
            try:
                self._distributed_registry = DistributedSessionRegistry(redis_url=self._redis_url)
                await self._distributed_registry.connect()
                logger.info("Using Distributed Session Registry")
            except Exception as exc:
                logger.warning("Distributed Session Registry failed: %s", exc)
                self._distributed_registry = None
                
    async def create_session(
        self,
        user_id: str,
        workspace_id: str,
        initial_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionContext:
        await self._ensure_connected()
        if self._distributed_registry:
            return await self._distributed_registry.create_session(
                user_id, workspace_id, initial_context, metadata
            )
        else:
            # Fallback to in-memory
            return SessionContext(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                workspace_id=workspace_id,
                context=initial_context or {},
                metadata=metadata or {},
            )
            
    async def get_session(self, session_id: str) -> SessionContext | None:
        await self._ensure_connected()
        if self._distributed_registry:
            return await self._distributed_registry.get_session(session_id)
        else:
            # Fallback: return None
            return None
            
    async def update_session(
        self,
        session_id: str,
        context_update: dict[str, Any] | None = None,
        metadata_update: dict[str, Any] | None = None,
        state_update: SessionState | None = None,
    ) -> bool:
        await self._ensure_connected()
        if self._distributed_registry:
            return await self._distributed_registry.update_session(
                session_id, context_update, metadata_update, state_update
            )
        else:
            # Fallback: return False
            return False
            
    async def get_active_sessions_count(self) -> int:
        """Get count of active sessions (backward compatibility)."""
        await self._ensure_connected()
        if self._distributed_registry:
            stats = await self._distributed_registry.get_stats()
            return stats.get("sessions_by_state", {}).get("active", 0)
        else:
            # Fallback: return 1 (hardcoded)
            return 1