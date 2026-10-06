"""Multi-User System - Comprehensive user management and collaboration.

This system provides:
- User authentication and authorization
- Role-based access control
- Session management
- User collaboration features
- Resource sharing
- Activity tracking
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt

from backend.observability.event_system import Event, EventBus, EventPriority, EventType

logger = logging.getLogger(__name__)


class UserRole(StrEnum):
    """User roles."""
    ADMIN = "admin"
    MODERATOR = "moderator"
    DEVELOPER = "developer"
    ANALYST = "analyst"
    USER = "user"
    GUEST = "guest"


class UserStatus(StrEnum):
    """User status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BANNED = "banned"


class SessionStatus(StrEnum):
    """Session status."""
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"


@dataclass
class User:
    """User account."""
    user_id: str = field(default_factory=lambda: f"user-{uuid.uuid4().hex[:12]}")
    username: str = ""
    email: str = ""
    password_hash: str = ""
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    
    # Profile
    first_name: str = ""
    last_name: str = ""
    avatar_url: str = ""
    bio: str = ""
    timezone: str = "UTC"
    language: str = "en"
    
    # Permissions
    permissions: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    
    # Activity
    last_login: datetime | None = None
    login_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (without sensitive data)."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "status": self.status.value,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "avatar_url": self.avatar_url,
            "bio": self.bio,
            "timezone": self.timezone,
            "language": self.language,
            "permissions": list(self.permissions),
            "groups": list(self.groups),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "login_count": self.login_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class Session:
    """User session."""
    session_id: str = field(default_factory=lambda: f"sess-{uuid.uuid4().hex[:12]}")
    user_id: str = ""
    token: str = ""
    refresh_token: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    
    # Session details
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=24))
    last_activity: datetime = field(default_factory=datetime.now)
    
    # Connection details
    ip_address: str = ""
    user_agent: str = ""
    device_info: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "device_info": self.device_info
        }


@dataclass
class UserGroup:
    """User group for collaboration."""
    group_id: str = field(default_factory=lambda: f"group-{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    created_by: str = ""
    
    # Group settings
    is_private: bool = False
    max_members: int = 100
    permissions: set[str] = field(default_factory=set)
    
    # Membership
    members: set[str] = field(default_factory=set)
    admins: set[str] = field(default_factory=set)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "group_id": self.group_id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "is_private": self.is_private,
            "max_members": self.max_members,
            "permissions": list(self.permissions),
            "members": list(self.members),
            "admins": list(self.admins),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class ActivityLog:
    """User activity log."""
    activity_id: str = field(default_factory=lambda: f"act-{uuid.uuid4().hex[:12]}")
    user_id: str = ""
    action: str = ""
    resource_type: str = ""
    resource_id: str = ""
    
    # Activity details
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    timestamp: datetime = field(default_factory=datetime.now)
    ip_address: str = ""
    user_agent: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "activity_id": self.activity_id,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "description": self.description,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent
        }


class MultiUserSystem:
    """Multi-user management system."""
    
    def __init__(self, event_bus: EventBus, jwt_secret: str = None):
        self.event_bus = event_bus
        self.jwt_secret = jwt_secret or secrets.token_urlsafe(32)
        
        # Storage
        self.users: dict[str, User] = {}
        self.sessions: dict[str, Session] = {}
        self.groups: dict[str, UserGroup] = {}
        self.activity_logs: list[ActivityLog] = []
        
        # Indexes
        self.username_to_id: dict[str, str] = {}
        self.email_to_id: dict[str, str] = {}
        self.user_sessions: dict[str, set[str]] = defaultdict(set)
        self.group_members: dict[str, set[str]] = defaultdict(set)
        
        # Settings
        self.session_timeout = timedelta(hours=24)
        self.max_sessions_per_user = 5
        self.password_min_length = 8
        
        # Statistics
        self.stats = {
            "total_users": 0,
            "active_users": 0,
            "total_sessions": 0,
            "active_sessions": 0,
            "total_groups": 0,
            "total_activities": 0
        }
        
        # Default permissions
        self.role_permissions = {
            UserRole.ADMIN: {
                "user.create", "user.read", "user.update", "user.delete",
                "group.create", "group.read", "group.update", "group.delete",
                "system.configure", "system.monitor", "system.admin"
            },
            UserRole.MODERATOR: {
                "user.read", "user.update", "user.suspend",
                "group.create", "group.read", "group.update",
                "content.moderate", "system.monitor"
            },
            UserRole.DEVELOPER: {
                "user.read", "group.read", "group.create",
                "code.execute", "code.deploy", "system.monitor"
            },
            UserRole.ANALYST: {
                "user.read", "group.read",
                "data.read", "analytics.read", "reports.read"
            },
            UserRole.USER: {
                "user.read", "group.read", "group.create",
                "content.create", "content.read", "content.update"
            },
            UserRole.GUEST: {
                "content.read", "group.read"
            }
        }
    
    async def create_user(self, username: str, email: str, password: str,
                         role: UserRole = UserRole.USER,
                         first_name: str = "", last_name: str = "") -> str:
        """Create a new user account."""
        try:
            # Validate input
            if not username or not email or not password:
                raise ValueError("Username, email, and password are required")
            
            if len(password) < self.password_min_length:
                raise ValueError(f"Password must be at least {self.password_min_length} characters")
            
            # Check for existing user
            if username in self.username_to_id:
                raise ValueError("Username already exists")
            
            if email in self.email_to_id:
                raise ValueError("Email already exists")
            
            # Create user
            user = User(
                username=username,
                email=email,
                password_hash=self._hash_password(password),
                role=role,
                first_name=first_name,
                last_name=last_name,
                permissions=self.role_permissions[role]
            )
            
            # Store user
            self.users[user.user_id] = user
            self.username_to_id[username] = user.user_id
            self.email_to_id[email] = user.user_id
            self.stats["total_users"] += 1
            
            # Log activity
            await self._log_activity(
                user_id=user.user_id,
                action="user.created",
                resource_type="user",
                resource_id=user.user_id,
                description=f"User account created: {username}"
            )
            
            # Emit event
            await self._emit_user_event("user_created", user)
            
            logger.info(f"User created: {username} ({user.user_id})")
            return user.user_id
            
        except Exception as e:
            logger.error(f"Failed to create user {username}: {e}")
            raise
    
    async def authenticate_user(self, username: str, password: str,
                              ip_address: str = "", user_agent: str = "") -> Session | None:
        """Authenticate user and create session."""
        try:
            # Get user
            user_id = self.username_to_id.get(username)
            if not user_id:
                return None
            
            user = self.users.get(user_id)
            if not user:
                return None
            
            # Check status
            if user.status != UserStatus.ACTIVE:
                return None
            
            # Verify password
            if not self._verify_password(password, user.password_hash):
                await self._log_activity(
                    user_id=user_id,
                    action="auth.failed",
                    resource_type="user",
                    resource_id=user_id,
                    description=f"Failed login attempt for {username}",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return None
            
            # Check session limit
            active_sessions = [s for s in self.sessions.values() 
                             if s.user_id == user_id and s.status == SessionStatus.ACTIVE]
            
            if len(active_sessions) >= self.max_sessions_per_user:
                # Terminate oldest session
                oldest_session = min(active_sessions, key=lambda s: s.created_at)
                await self.terminate_session(oldest_session.session_id)
            
            # Create session
            session = Session(
                user_id=user_id,
                token=self._generate_token(user_id),
                refresh_token=self._generate_token(user_id, refresh=True),
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            # Store session
            self.sessions[session.session_id] = session
            self.user_sessions[user_id].add(session.session_id)
            self.stats["total_sessions"] += 1
            self.stats["active_sessions"] += 1
            
            # Update user
            user.last_login = datetime.now()
            user.login_count += 1
            user.updated_at = datetime.now()
            
            # Log activity
            await self._log_activity(
                user_id=user_id,
                action="auth.success",
                resource_type="user",
                resource_id=user_id,
                description=f"User logged in: {username}",
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            # Emit event
            await self._emit_user_event("user_logged_in", user, session)
            
            logger.info(f"User authenticated: {username}")
            return session
            
        except Exception as e:
            logger.error(f"Failed to authenticate user {username}: {e}")
            return None
    
    async def validate_session(self, token: str) -> User | None:
        """Validate session token and return user."""
        try:
            # Decode token
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            user_id = payload.get("user_id")
            
            if not user_id:
                return None
            
            # Find session
            session = None
            for sess in self.sessions.values():
                if sess.token == token and sess.status == SessionStatus.ACTIVE:
                    session = sess
                    break
            
            if not session:
                return None
            
            # Check expiration
            if datetime.now() > session.expires_at:
                await self.terminate_session(session.session_id)
                return None
            
            # Update last activity
            session.last_activity = datetime.now()
            
            # Get user
            user = self.users.get(user_id)
            if not user or user.status != UserStatus.ACTIVE:
                return None
            
            return user
            
        except jwt.InvalidTokenError:
            return None
        except Exception as e:
            logger.error(f"Failed to validate session: {e}")
            return None
    
    async def terminate_session(self, session_id: str) -> bool:
        """Terminate a user session."""
        try:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            # Update session
            session.status = SessionStatus.TERMINATED
            self.stats["active_sessions"] -= 1
            
            # Remove from user sessions
            if session.user_id in self.user_sessions:
                self.user_sessions[session.user_id].discard(session_id)
            
            # Log activity
            await self._log_activity(
                user_id=session.user_id,
                action="session.terminated",
                resource_type="session",
                resource_id=session_id,
                description=f"Session terminated: {session_id}"
            )
            
            # Emit event
            await self._emit_session_event("session_terminated", session)
            
            logger.info(f"Session terminated: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to terminate session {session_id}: {e}")
            return False
    
    async def create_group(self, name: str, description: str, created_by: str,
                         is_private: bool = False, max_members: int = 100) -> str:
        """Create a new user group."""
        try:
            # Validate creator
            creator = self.users.get(created_by)
            if not creator:
                raise ValueError("Creator not found")
            
            # Create group
            group = UserGroup(
                name=name,
                description=description,
                created_by=created_by,
                is_private=is_private,
                max_members=max_members
            )
            
            # Add creator as admin
            group.members.add(created_by)
            group.admins.add(created_by)
            
            # Store group
            self.groups[group.group_id] = group
            self.group_members[group.group_id].add(created_by)
            self.stats["total_groups"] += 1
            
            # Update user groups
            creator.groups.add(group.group_id)
            creator.updated_at = datetime.now()
            
            # Log activity
            await self._log_activity(
                user_id=created_by,
                action="group.created",
                resource_type="group",
                resource_id=group.group_id,
                description=f"Group created: {name}"
            )
            
            # Emit event
            await self._emit_group_event("group_created", group)
            
            logger.info(f"Group created: {name} ({group.group_id})")
            return group.group_id
            
        except Exception as e:
            logger.error(f"Failed to create group {name}: {e}")
            raise
    
    async def join_group(self, group_id: str, user_id: str) -> bool:
        """Add user to group."""
        try:
            # Validate
            group = self.groups.get(group_id)
            user = self.users.get(user_id)
            
            if not group or not user:
                return False
            
            # Check capacity
            if len(group.members) >= group.max_members:
                return False
            
            # Add to group
            group.members.add(user_id)
            self.group_members[group_id].add(user_id)
            user.groups.add(group_id)
            
            # Update timestamps
            group.updated_at = datetime.now()
            user.updated_at = datetime.now()
            
            # Log activity
            await self._log_activity(
                user_id=user_id,
                action="group.joined",
                resource_type="group",
                resource_id=group_id,
                description=f"User {user.username} joined group {group.name}"
            )
            
            # Emit event
            await self._emit_group_event("user_joined", group, user)
            
            logger.info(f"User {user.username} joined group {group.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to join group {group_id}: {e}")
            return False
    
    async def leave_group(self, group_id: str, user_id: str) -> bool:
        """Remove user from group."""
        try:
            # Validate
            group = self.groups.get(group_id)
            user = self.users.get(user_id)
            
            if not group or not user:
                return False
            
            # Remove from group
            group.members.discard(user_id)
            group.admins.discard(user_id)
            self.group_members[group_id].discard(user_id)
            user.groups.discard(group_id)
            
            # Update timestamps
            group.updated_at = datetime.now()
            user.updated_at = datetime.now()
            
            # Log activity
            await self._log_activity(
                user_id=user_id,
                action="group.left",
                resource_type="group",
                resource_id=group_id,
                description=f"User {user.username} left group {group.name}"
            )
            
            # Emit event
            await self._emit_group_event("user_left", group, user)
            
            logger.info(f"User {user.username} left group {group.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to leave group {group_id}: {e}")
            return False
    
    async def get_user(self, user_id: str) -> User | None:
        """Get user by ID."""
        return self.users.get(user_id)
    
    async def get_user_by_username(self, username: str) -> User | None:
        """Get user by username."""
        user_id = self.username_to_id.get(username)
        return self.users.get(user_id) if user_id else None
    
    async def get_users(self, status: UserStatus | None = None,
                       role: UserRole | None = None,
                       limit: int = 100) -> list[User]:
        """Get users with optional filtering."""
        users = list(self.users.values())
        
        # Apply filters
        if status:
            users = [u for u in users if u.status == status]
        if role:
            users = [u for u in users if u.role == role]
        
        # Sort and limit
        users.sort(key=lambda u: u.created_at, reverse=True)
        return users[:limit]
    
    async def get_groups(self, user_id: str | None = None,
                       limit: int = 100) -> list[UserGroup]:
        """Get groups with optional filtering."""
        groups = list(self.groups.values())
        
        # Filter by user membership
        if user_id:
            groups = [g for g in groups if user_id in g.members]
        
        # Sort and limit
        groups.sort(key=lambda g: g.created_at, reverse=True)
        return groups[:limit]
    
    async def get_activity_logs(self, user_id: str | None = None,
                              action: str | None = None,
                              limit: int = 100) -> list[ActivityLog]:
        """Get activity logs with optional filtering."""
        logs = self.activity_logs
        
        # Apply filters
        if user_id:
            logs = [entry for entry in logs if entry.user_id == user_id]
        if action:
            logs = [entry for entry in logs if entry.action == action]
        
        # Sort and limit
        logs.sort(key=lambda entry: entry.timestamp, reverse=True)
        return logs[:limit]
    
    async def get_user_stats(self) -> dict[str, Any]:
        """Get user system statistics."""
        # Update statistics
        self.stats["active_users"] = len([u for u in self.users.values() if u.status == UserStatus.ACTIVE])
        self.stats["active_sessions"] = len([s for s in self.sessions.values() if s.status == SessionStatus.ACTIVE])
        
        return {
            "stats": self.stats,
            "role_distribution": {
                role.value: len([u for u in self.users.values() if u.role == role])
                for role in UserRole
            },
            "status_distribution": {
                status.value: len([u for u in self.users.values() if u.status == status])
                for status in UserStatus
            },
            "average_login_count": sum(u.login_count for u in self.users.values()) / len(self.users) if self.users else 0
        }
    
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt-like method."""
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return f"{salt}:{password_hash.hex()}"
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash."""
        try:
            salt, hash_hex = password_hash.split(':')
            computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return hmac.compare_digest(computed_hash.hex(), hash_hex)
        except (ValueError, AttributeError, TypeError):
            # A malformed stored hash must fail closed, not crash. Bare `except:`
            # also swallowed KeyboardInterrupt and SystemExit, which made this
            # impossible to Ctrl-C and hid real bugs (E722).
            return False
    
    def _generate_token(self, user_id: str, refresh: bool = False) -> str:
        """Generate JWT token."""
        expires_in = 30 * 24 * 60 * 60 if refresh else 60 * 60  # 30 days for refresh, 1 hour for access
        
        payload = {
            "user_id": user_id,
            "refresh": refresh,
            "exp": datetime.now() + timedelta(seconds=expires_in),
            "iat": datetime.now()
        }
        
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")
    
    async def _log_activity(self, user_id: str, action: str, resource_type: str,
                          resource_id: str, description: str,
                          ip_address: str = "", user_agent: str = "",
                          metadata: dict[str, Any] = None) -> None:
        """Log user activity."""
        activity = ActivityLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {}
        )
        
        self.activity_logs.append(activity)
        self.stats["total_activities"] += 1
        
        # Keep only recent logs (last 10000)
        if len(self.activity_logs) > 10000:
            self.activity_logs = self.activity_logs[-10000:]
    
    async def _emit_user_event(self, event_type: str, user: User, session: Session = None) -> None:
        """Emit user-related event."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=EventType.USER_ACTIVITY,
                source="multi_user_system",
                priority=EventPriority.NORMAL,
                payload={
                    "event_type": event_type,
                    "user": user.to_dict(),
                    "session": session.to_dict() if session else None
                },
                metadata={
                    "component": "multi_user_system",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit user event: {e}")
    
    async def _emit_session_event(self, event_type: str, session: Session) -> None:
        """Emit session-related event."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=EventType.SESSION_ACTIVITY,
                source="multi_user_system",
                priority=EventPriority.NORMAL,
                payload={
                    "event_type": event_type,
                    "session": session.to_dict()
                },
                metadata={
                    "component": "multi_user_system",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit session event: {e}")
    
    async def _emit_group_event(self, event_type: str, group: UserGroup, user: User = None) -> None:
        """Emit group-related event."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=EventType.GROUP_ACTIVITY,
                source="multi_user_system",
                priority=EventPriority.NORMAL,
                payload={
                    "event_type": event_type,
                    "group": group.to_dict(),
                    "user": user.to_dict() if user else None
                },
                metadata={
                    "component": "multi_user_system",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit group event: {e}")


# Global multi-user system instance
_multi_user_system: MultiUserSystem | None = None


async def get_multi_user_system(event_bus: EventBus, jwt_secret: str = None) -> MultiUserSystem:
    """Get the global multi-user system instance."""
    global _multi_user_system
    if _multi_user_system is None:
        _multi_user_system = MultiUserSystem(event_bus, jwt_secret)
    return _multi_user_system


async def shutdown_multi_user_system() -> None:
    """Shutdown the multi-user system."""
    global _multi_user_system
    if _multi_user_system:
        # Terminate all active sessions
        for session in list(_multi_user_system.sessions.values()):
            if session.status == SessionStatus.ACTIVE:
                await _multi_user_system.terminate_session(session.session_id)
        
        _multi_user_system = None