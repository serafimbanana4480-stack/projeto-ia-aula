"""Enterprise Security Hardening System.

Implements authentication, authorization, encryption, audit logging,
vulnerability scanning, and security monitoring.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import hashlib
import hmac
import secrets
import jwt
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Callable
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class SecurityLevel(str, Enum):
    """Security levels for operations."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"
    TOP_SECRET = "top_secret"


class ThreatLevel(str, Enum):
    """Threat severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VulnerabilityType(str, Enum):
    """Types of security vulnerabilities."""
    SQL_INJECTION = "sql_injection"
    XSS = "xss"
    CSRF = "csrf"
    AUTHENTICATION_BYPASS = "authentication_bypass"
    AUTHORIZATION_BYPASS = "authorization_bypass"
    DATA_EXPOSURE = "data_exposure"
    DENIAL_OF_SERVICE = "denial_of_service"
    INSECURE_CRYPTO = "insecure_crypto"
    INSECURE_CONFIG = "insecure_config"
    PRIVILEGE_ESCALATION = "privilege_escalation"


@dataclass
class SecurityPolicy:
    """Security policy definition."""
    policy_id: str = field(default_factory=lambda: f"policy-{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    
    # Policy rules
    rules: List[Dict[str, Any]] = field(default_factory=list)
    
    # Scope
    components: List[str] = field(default_factory=list)
    operations: List[str] = field(default_factory=list)
    
    # Enforcement
    enforcement_level: str = "strict"  # strict, moderate, advisory
    exceptions: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "rules": self.rules,
            "components": self.components,
            "operations": self.operations,
            "enforcement_level": self.enforcement_level,
            "exceptions": self.exceptions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }


@dataclass
class SecurityEvent:
    """Security event for audit logging."""
    event_id: str = field(default_factory=lambda: f"event-{uuid.uuid4().hex[:12]}")
    event_type: str = ""
    severity: ThreatLevel = ThreatLevel.LOW
    
    # Event details
    source: str = ""
    target: str = ""
    action: str = ""
    result: str = ""
    
    # Context
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "severity": self.severity.value,
            "source": self.source,
            "target": self.target,
            "action": self.action,
            "result": self.result,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class Vulnerability:
    """Security vulnerability detection."""
    vulnerability_id: str = field(default_factory=lambda: f"vuln-{uuid.uuid4().hex[:12]}")
    title: str = ""
    description: str = ""
    
    # Classification
    vulnerability_type: VulnerabilityType = VulnerabilityType.DATA_EXPOSURE
    severity: ThreatLevel = ThreatLevel.MEDIUM
    cvss_score: float = 0.0  # 0.0-10.0
    
    # Location
    component: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    
    # Detection
    detected_at: float = field(default_factory=time.time)
    scanner: str = ""
    evidence: List[str] = field(default_factory=list)
    
    # Status
    status: str = "open"  # open, investigating, fixed, verified
    fixed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "vulnerability_id": self.vulnerability_id,
            "title": self.title,
            "description": self.description,
            "vulnerability_type": self.vulnerability_type.value,
            "severity": self.severity.value,
            "cvss_score": self.cvss_score,
            "component": self.component,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "detected_at": self.detected_at,
            "scanner": self.scanner,
            "evidence": self.evidence,
            "status": self.status,
            "fixed_at": self.fixed_at,
        }


@dataclass
class SecurityToken:
    """Security token for authentication."""
    token_id: str = field(default_factory=lambda: f"token-{uuid.uuid4().hex[:12]}")
    user_id: str = ""
    token_type: str = "jwt"  # jwt, api_key, session
    
    # Token data
    token: str = ""
    refresh_token: Optional[str] = None
    
    # Permissions
    permissions: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    
    # Lifecycle
    issued_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)  # 1 hour
    last_used: float = field(default_factory=time.time)
    
    # Security
    is_revoked: bool = False
    revoked_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "user_id": self.user_id,
            "token_type": self.token_type,
            "permissions": self.permissions,
            "roles": self.roles,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "last_used": self.last_used,
            "is_revoked": self.is_revoked,
            "revoked_at": self.revoked_at,
        }


class AuthenticationManager:
    """Authentication and authorization management."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", jwt_secret: str = None):
        self.redis_url = redis_url
        self.jwt_secret = jwt_secret or secrets.token_urlsafe(32)
        self._redis: Optional[redis.Redis] = None
        
        # Token storage
        self.tokens: Dict[str, SecurityToken] = {}
        
        # User storage (in production, use proper database)
        self.users: Dict[str, Dict[str, Any]] = {}
        
        # Rate limiting
        self.login_attempts: Dict[str, List[float]] = defaultdict(list)
        
    async def initialize(self) -> None:
        """Initialize authentication manager."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing tokens
        await self._load_tokens()
        
        # Setup default users
        await self._setup_default_users()
        
        logger.info("AuthenticationManager initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_tokens(self) -> None:
        """Load existing tokens from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="auth_tokens:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        token_data = json.loads(data)
                        token = SecurityToken(**token_data)
                        self.tokens[token.token_id] = token
                        
        except Exception as exc:
            logger.error("Failed to load tokens: %s", exc)
            
    async def _setup_default_users(self) -> None:
        """Setup default users for development."""
        if not self.users:
            # Create admin user
            admin_password = self._hash_password("admin123")
            self.users["admin"] = {
                "user_id": "admin",
                "username": "admin",
                "password_hash": admin_password,
                "roles": ["admin", "user"],
                "permissions": ["*"],
                "created_at": time.time(),
                "is_active": True,
            }
            
            # Create regular user
            user_password = self._hash_password("user123")
            self.users["user"] = {
                "user_id": "user",
                "username": "user",
                "password_hash": user_password,
                "roles": ["user"],
                "permissions": ["read", "write"],
                "created_at": time.time(),
                "is_active": True,
            }
            
    def _hash_password(self, password: str) -> str:
        """Hash password with PBKDF2."""
        salt = secrets.token_bytes(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(password.encode())
        return base64.urlsafe_b64encode(key + salt).decode()
        
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash."""
        try:
            decoded = base64.urlsafe_b64decode(password_hash.encode())
            key = decoded[:32]
            salt = decoded[32:]
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            try:
                kdf.verify(password.encode(), key)
                return True
            except:
                return False
        except:
            return False
            
    async def authenticate(self, username: str, password: str, ip_address: str = "") -> Optional[SecurityToken]:
        """Authenticate user and create token."""
        # Check rate limiting
        if not await self._check_rate_limit(username, ip_address):
            raise SecurityException("Too many login attempts")
            
        # Verify credentials
        user = self.users.get(username)
        if not user or not user["is_active"]:
            raise SecurityException("Invalid credentials")
            
        if not self._verify_password(password, user["password_hash"]):
            await self._record_failed_attempt(username, ip_address)
            raise SecurityException("Invalid credentials")
            
        # Create token
        token = SecurityToken(
            user_id=user["user_id"],
            token_type="jwt",
            permissions=user["permissions"],
            roles=user["roles"],
        )
        
        # Generate JWT
        payload = {
            "user_id": user["user_id"],
            "username": username,
            "roles": user["roles"],
            "permissions": user["permissions"],
            "iat": int(token.issued_at),
            "exp": int(token.expires_at),
            "jti": token.token_id,
        }
        
        token.token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
        
        # Store token
        self.tokens[token.token_id] = token
        
        # Store in Redis
        if self._redis:
            key = f"auth_tokens:{token.token_id}"
            await self._redis.setex(key, 3600, json.dumps(token.to_dict()))  # 1 hour
            
        # Clear failed attempts
        self.login_attempts[username] = []
        
        return token
        
    async def _check_rate_limit(self, username: str, ip_address: str) -> bool:
        """Check rate limiting for login attempts."""
        current_time = time.time()
        
        # Check username attempts
        user_attempts = self.login_attempts.get(username, [])
        user_attempts = [t for t in user_attempts if current_time - t < 900]  # 15 minutes
        self.login_attempts[username] = user_attempts
        
        if len(user_attempts) >= 5:
            return False
            
        # Check IP attempts
        ip_key = f"ip_{ip_address}"
        ip_attempts = self.login_attempts.get(ip_key, [])
        ip_attempts = [t for t in ip_attempts if current_time - t < 900]  # 15 minutes
        self.login_attempts[ip_key] = ip_attempts
        
        if len(ip_attempts) >= 10:
            return False
            
        return True
        
    async def _record_failed_attempt(self, username: str, ip_address: str) -> None:
        """Record failed login attempt."""
        current_time = time.time()
        
        # Record username attempt
        if username not in self.login_attempts:
            self.login_attempts[username] = []
        self.login_attempts[username].append(current_time)
        
        # Record IP attempt
        ip_key = f"ip_{ip_address}"
        if ip_key not in self.login_attempts:
            self.login_attempts[ip_key] = []
        self.login_attempts[ip_key].append(current_time)
        
    async def verify_token(self, token: str) -> Optional[SecurityToken]:
        """Verify JWT token."""
        try:
            # Decode JWT
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            token_id = payload.get("jti")
            
            if not token_id:
                return None
                
            # Get token from storage
            security_token = self.tokens.get(token_id)
            if not security_token:
                return None
                
            # Check if revoked
            if security_token.is_revoked:
                return None
                
            # Check expiration
            if time.time() > security_token.expires_at:
                await self.revoke_token(token_id)
                return None
                
            # Update last used
            security_token.last_used = time.time()
            
            return security_token
            
        except jwt.InvalidTokenError:
            return None
            
    async def revoke_token(self, token_id: str) -> bool:
        """Revoke security token."""
        if token_id not in self.tokens:
            return False
            
        token = self.tokens[token_id]
        token.is_revoked = True
        token.revoked_at = time.time()
        
        # Update Redis
        if self._redis:
            key = f"auth_tokens:{token_id}"
            await self._redis.delete(key)
            
        return True
        
    def has_permission(self, token: SecurityToken, permission: str) -> bool:
        """Check if token has permission."""
        # Wildcard permission
        if "*" in token.permissions:
            return True
            
        # Direct permission
        if permission in token.permissions:
            return True
            
        # Role-based permissions
        for role in token.roles:
            role_permissions = self._get_role_permissions(role)
            if permission in role_permissions:
                return True
                
        return False
        
    def _get_role_permissions(self, role: str) -> List[str]:
        """Get permissions for role."""
        role_permissions = {
            "admin": ["*"],
            "user": ["read", "write"],
            "readonly": ["read"],
        }
        return role_permissions.get(role, [])


class EncryptionManager:
    """Data encryption and decryption management."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Encryption keys
        self.master_key: Optional[bytes] = None
        self.data_keys: Dict[str, bytes] = {}
        
    async def initialize(self) -> None:
        """Initialize encryption manager."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Generate or load master key
        await self._setup_master_key()
        
        logger.info("EncryptionManager initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _setup_master_key(self) -> None:
        """Setup master encryption key."""
        # Try to load from Redis
        if self._redis:
            stored_key = await self._redis.get("encryption:master_key")
            if stored_key:
                self.master_key = base64.urlsafe_b64decode(stored_key.encode())
                return
                
        # Generate new master key
        self.master_key = Fernet.generate_key()
        
        # Store in Redis
        if self._redis:
            await self._redis.set("encryption:master_key", base64.urlsafe_b64encode(self.master_key).decode())
            
    async def get_data_key(self, key_id: str) -> bytes:
        """Get or create data encryption key."""
        if key_id in self.data_keys:
            return self.data_keys[key_id]
            
        # Try to load from Redis
        if self._redis:
            stored_key = await self._redis.get(f"encryption:data_key:{key_id}")
            if stored_key:
                key = base64.urlsafe_b64decode(stored_key.encode())
                self.data_keys[key_id] = key
                return key
                
        # Generate new data key
        key = Fernet.generate_key()
        self.data_keys[key_id] = key
        
        # Store in Redis
        if self._redis:
            await self._redis.set(f"encryption:data_key:{key_id}", base64.urlsafe_b64encode(key).decode())
            
        return key
        
    async def encrypt(self, data: str, key_id: str = "default") -> str:
        """Encrypt data."""
        if not self.master_key:
            raise SecurityException("Encryption not initialized")
            
        # Get data key
        data_key = await self.get_data_key(key_id)
        fernet = Fernet(data_key)
        
        # Encrypt data
        encrypted_data = fernet.encrypt(data.encode())
        
        # Return base64 encoded
        return base64.urlsafe_b64encode(encrypted_data).decode()
        
    async def decrypt(self, encrypted_data: str, key_id: str = "default") -> str:
        """Decrypt data."""
        if not self.master_key:
            raise SecurityException("Encryption not initialized")
            
        try:
            # Get data key
            data_key = await self.get_data_key(key_id)
            fernet = Fernet(data_key)
            
            # Decode and decrypt
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_data = fernet.decrypt(encrypted_bytes)
            
            return decrypted_data.decode()
            
        except Exception as exc:
            raise SecurityException(f"Decryption failed: {exc}")
            
    async def encrypt_field(self, value: Any, key_id: str = "default") -> str:
        """Encrypt a field value."""
        if value is None:
            return ""
            
        # Convert to JSON
        json_data = json.dumps(value)
        
        # Encrypt
        return await self.encrypt(json_data, key_id)
        
    async def decrypt_field(self, encrypted_value: str, key_id: str = "default") -> Any:
        """Decrypt a field value."""
        if not encrypted_value:
            return None
            
        # Decrypt
        json_data = await self.decrypt(encrypted_value, key_id)
        
        # Parse JSON
        return json.loads(json_data)


class AuditLogger:
    """Security audit logging system."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Event storage
        self.events: List[SecurityEvent] = []
        
        # Event handlers
        self.event_handlers: List[Callable] = []
        
    async def initialize(self) -> None:
        """Initialize audit logger."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing events
        await self._load_events()
        
        logger.info("AuditLogger initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_events(self) -> None:
        """Load existing events from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="audit_events:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        event_data = json.loads(data)
                        event = SecurityEvent(**event_data)
                        self.events.append(event)
                        
            # Keep only last 10000 events
            if len(self.events) > 10000:
                self.events = self.events[-10000:]
                
        except Exception as exc:
            logger.error("Failed to load events: %s", exc)
            
    async def log_event(
        self,
        event_type: str,
        severity: ThreatLevel,
        source: str,
        target: str,
        action: str,
        result: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log security event."""
        event = SecurityEvent(
            event_type=event_type,
            severity=severity,
            source=source,
            target=target,
            action=action,
            result=result,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {},
        )
        
        # Store event
        self.events.append(event)
        
        # Keep only last 10000 events
        if len(self.events) > 10000:
            self.events = self.events[-10000:]
            
        # Store in Redis
        if self._redis:
            key = f"audit_events:{event.event_id}"
            await self._redis.setex(key, 86400 * 30, json.dumps(event.to_dict()))  # 30 days
            
        # Notify handlers
        await self._notify_handlers(event)
        
        return event.event_id
        
    async def _notify_handlers(self, event: SecurityEvent) -> None:
        """Notify event handlers."""
        for handler in self.event_handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.error("Event handler error: %s", exc)
                
    def get_events(
        self,
        event_type: Optional[str] = None,
        severity: Optional[ThreatLevel] = None,
        user_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100
    ) -> List[SecurityEvent]:
        """Get filtered events."""
        events = self.events
        
        # Apply filters
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if severity:
            events = [e for e in events if e.severity == severity]
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]
            
        # Sort by timestamp and limit
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]
        
    def get_security_summary(self) -> Dict[str, Any]:
        """Get security summary."""
        total_events = len(self.events)
        
        # Count by severity
        severity_counts = {}
        for severity in ThreatLevel:
            count = len([e for e in self.events if e.severity == severity])
            severity_counts[severity.value] = count
            
        # Count by event type
        event_type_counts = {}
        for event in self.events:
            event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1
            
        # Recent threats (last 24 hours)
        recent_time = time.time() - 86400
        recent_threats = [e for e in self.events if e.timestamp >= recent_time and e.severity in [ThreatLevel.HIGH, ThreatLevel.CRITICAL]]
        
        return {
            "total_events": total_events,
            "severity_counts": severity_counts,
            "event_type_counts": event_type_counts,
            "recent_threats": len(recent_threats),
            "latest_event": self.events[-1].timestamp if self.events else None,
        }


class VulnerabilityScanner:
    """Security vulnerability scanner."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Vulnerability storage
        self.vulnerabilities: List[Vulnerability] = []
        
        # Scanning rules
        self.scanning_rules: List[Dict[str, Any]] = []
        
    async def initialize(self) -> None:
        """Initialize vulnerability scanner."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing vulnerabilities
        await self._load_vulnerabilities()
        
        # Setup scanning rules
        self._setup_scanning_rules()
        
        logger.info("VulnerabilityScanner initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _load_vulnerabilities(self) -> None:
        """Load existing vulnerabilities from Redis."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="vulnerabilities:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        vuln_data = json.loads(data)
                        vulnerability = Vulnerability(**vuln_data)
                        self.vulnerabilities.append(vulnerability)
                        
        except Exception as exc:
            logger.error("Failed to load vulnerabilities: %s", exc)
            
    def _setup_scanning_rules(self) -> None:
        """Setup vulnerability scanning rules."""
        self.scanning_rules = [
            {
                "name": "hardcoded_secrets",
                "type": VulnerabilityType.DATA_EXPOSURE,
                "pattern": r"(password|secret|key|token)\s*=\s*['\"][^'\"]{8,}['\"]",
                "severity": ThreatLevel.HIGH,
                "description": "Hardcoded secrets detected"
            },
            {
                "name": "sql_injection",
                "type": VulnerabilityType.SQL_INJECTION,
                "pattern": r"(execute|query)\s*\(\s*['\"].*\+\s*.*['\"]",
                "severity": ThreatLevel.CRITICAL,
                "description": "Potential SQL injection vulnerability"
            },
            {
                "name": "weak_crypto",
                "type": VulnerabilityType.INSECURE_CRYPTO,
                "pattern": r"(md5|sha1)\s*\(",
                "severity": ThreatLevel.MEDIUM,
                "description": "Weak cryptographic algorithm detected"
            },
            {
                "name": "debug_code",
                "type": VulnerabilityType.INSECURE_CONFIG,
                "pattern": r"(print|console\.log|debug)\s*\(",
                "severity": ThreatLevel.LOW,
                "description": "Debug code detected in production"
            }
        ]
        
    async def scan_code(self, code: str, file_path: str, component: str) -> List[Vulnerability]:
        """Scan code for vulnerabilities."""
        vulnerabilities = []
        lines = code.split('\n')
        
        for rule in self.scanning_rules:
            import re
            pattern = re.compile(rule["pattern"], re.IGNORECASE)
            
            for line_num, line in enumerate(lines, 1):
                if pattern.search(line):
                    vulnerability = Vulnerability(
                        title=f"{rule['name']} in {file_path}",
                        description=rule["description"],
                        vulnerability_type=rule["type"],
                        severity=rule["severity"],
                        component=component,
                        file_path=file_path,
                        line_number=line_num,
                        scanner="automated",
                        evidence=[line.strip()]
                    )
                    
                    vulnerabilities.append(vulnerability)
                    self.vulnerabilities.append(vulnerability)
                    
                    # Store in Redis
                    if self._redis:
                        key = f"vulnerabilities:{vulnerability.vulnerability_id}"
                        await self._redis.setex(key, 86400 * 30, json.dumps(vulnerability.to_dict()))  # 30 days
                        
        return vulnerabilities
        
    def get_vulnerabilities(
        self,
        vulnerability_type: Optional[VulnerabilityType] = None,
        severity: Optional[ThreatLevel] = None,
        component: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Vulnerability]:
        """Get filtered vulnerabilities."""
        vulns = self.vulnerabilities
        
        # Apply filters
        if vulnerability_type:
            vulns = [v for v in vulns if v.vulnerability_type == vulnerability_type]
        if severity:
            vulns = [v for v in vulns if v.severity == severity]
        if component:
            vulns = [v for v in vulns if v.component == component]
        if status:
            vulns = [v for v in vulns if v.status == status]
            
        # Sort by severity and detected time
        severity_order = {ThreatLevel.CRITICAL: 0, ThreatLevel.HIGH: 1, ThreatLevel.MEDIUM: 2, ThreatLevel.LOW: 3}
        vulns.sort(key=lambda v: (severity_order.get(v.severity, 4), v.detected_at), reverse=True)
        
        return vulns[:limit]
        
    def get_vulnerability_summary(self) -> Dict[str, Any]:
        """Get vulnerability summary."""
        total_vulns = len(self.vulnerabilities)
        
        # Count by severity
        severity_counts = {}
        for severity in ThreatLevel:
            count = len([v for v in self.vulnerabilities if v.severity == severity])
            severity_counts[severity.value] = count
            
        # Count by type
        type_counts = {}
        for vuln in self.vulnerabilities:
            type_counts[vuln.vulnerability_type.value] = type_counts.get(vuln.vulnerability_type.value, 0) + 1
            
        # Count by status
        status_counts = {}
        for vuln in self.vulnerabilities:
            status_counts[vuln.status] = status_counts.get(vuln.status, 0) + 1
            
        return {
            "total_vulnerabilities": total_vulns,
            "severity_counts": severity_counts,
            "type_counts": type_counts,
            "status_counts": status_counts,
            "open_vulnerabilities": len([v for v in self.vulnerabilities if v.status == "open"]),
            "critical_vulnerabilities": len([v for v in self.vulnerabilities if v.severity == ThreatLevel.CRITICAL]),
        }


class SecurityHardeningSystem:
    """Integrated security hardening system."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", jwt_secret: str = None):
        self.redis_url = redis_url
        self.jwt_secret = jwt_secret
        
        # Security components
        self.auth_manager = AuthenticationManager(redis_url, jwt_secret)
        self.encryption_manager = EncryptionManager(redis_url)
        self.audit_logger = AuditLogger(redis_url)
        self.vulnerability_scanner = VulnerabilityScanner(redis_url)
        
        # Security policies
        self.policies: List[SecurityPolicy] = []
        
        # Background tasks
        self.monitoring_task: Optional[asyncio.Task] = None
        
    async def initialize(self) -> None:
        """Initialize security system."""
        # Initialize components
        await self.auth_manager.initialize()
        await self.encryption_manager.initialize()
        await self.audit_logger.initialize()
        await self.vulnerability_scanner.initialize()
        
        # Setup default policies
        self._setup_default_policies()
        
        # Start background monitoring
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        logger.info("SecurityHardeningSystem initialized")
        
    async def shutdown(self) -> None:
        """Shutdown security system."""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            
        await self.auth_manager.disconnect()
        await self.encryption_manager.disconnect()
        await self.audit_logger.disconnect()
        await self.vulnerability_scanner.disconnect()
        
        logger.info("SecurityHardeningSystem shutdown")
        
    def _setup_default_policies(self) -> None:
        """Setup default security policies."""
        self.policies = [
            SecurityPolicy(
                name="Authentication Required",
                description="All API endpoints require authentication",
                rules=[
                    {"action": "require_auth", "endpoint": "/api/*"},
                    {"action": "rate_limit", "limit": 100, "window": 300}
                ],
                components=["api", "web"],
                operations=["*"],
                enforcement_level="strict"
            ),
            SecurityPolicy(
                name="Data Encryption",
                description="Sensitive data must be encrypted",
                rules=[
                    {"action": "encrypt_field", "field": "password"},
                    {"action": "encrypt_field", "field": "api_key"},
                    {"action": "encrypt_field", "field": "secret"}
                ],
                components=["database", "storage"],
                operations=["write", "update"],
                enforcement_level="strict"
            ),
            SecurityPolicy(
                name="Audit Logging",
                description="All security events must be logged",
                rules=[
                    {"action": "log_event", "event_type": "authentication"},
                    {"action": "log_event", "event_type": "authorization"},
                    {"action": "log_event", "event_type": "data_access"}
                ],
                components=["*"],
                operations=["*"],
                enforcement_level="strict"
            )
        ]
        
    async def _monitoring_loop(self) -> None:
        """Background security monitoring."""
        while True:
            try:
                await asyncio.sleep(60)  # Monitor every minute
                
                # Check for security events
                await self._check_security_events()
                
                # Scan for new vulnerabilities
                await self._scan_for_vulnerabilities()
                
                # Enforce policies
                await self._enforce_policies()
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Security monitoring error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _check_security_events(self) -> None:
        """Check for security events."""
        # Check for failed authentication attempts
        recent_events = self.audit_logger.get_events(
            event_type="authentication",
            start_time=time.time() - 300  # Last 5 minutes
        )
        
        failed_attempts = [e for e in recent_events if e.result == "failed"]
        if len(failed_attempts) > 10:
            await self.audit_logger.log_event(
                event_type="brute_force_attack",
                severity=ThreatLevel.HIGH,
                source="security_monitor",
                target="authentication",
                action="monitoring",
                result="detected",
                metadata={"failed_attempts": len(failed_attempts)}
            )
            
    async def _scan_for_vulnerabilities(self) -> None:
        """Scan for new vulnerabilities."""
        # This would scan codebase for vulnerabilities
        # For now, just check if we have critical vulnerabilities
        critical_vulns = self.vulnerability_scanner.get_vulnerabilities(
            severity=ThreatLevel.CRITICAL,
            status="open"
        )
        
        if critical_vulns:
            await self.audit_logger.log_event(
                event_type="vulnerability_detected",
                severity=ThreatLevel.CRITICAL,
                source="vulnerability_scanner",
                target="system",
                action="scanning",
                result="detected",
                metadata={"critical_vulnerabilities": len(critical_vulns)}
            )
            
    async def _enforce_policies(self) -> None:
        """Enforce security policies."""
        for policy in self.policies:
            if policy.enforcement_level == "strict":
                # Check policy compliance
                await self._check_policy_compliance(policy)
                
    async def _check_policy_compliance(self, policy: SecurityPolicy) -> None:
        """Check policy compliance."""
        # This would check if policy is being followed
        # For now, just log policy check
        await self.audit_logger.log_event(
            event_type="policy_check",
            severity=ThreatLevel.LOW,
            source="policy_enforcer",
            target=policy.name,
            action="compliance_check",
            result="checked"
        )
        
    def get_security_status(self) -> Dict[str, Any]:
        """Get comprehensive security status."""
        return {
            "authentication": {
                "active_tokens": len(self.auth_manager.tokens),
                "active_users": len([u for u in self.auth_manager.users.values() if u["is_active"]]),
            },
            "encryption": {
                "master_key_set": self.encryption_manager.master_key is not None,
                "data_keys": len(self.encryption_manager.data_keys),
            },
            "audit": self.audit_logger.get_security_summary(),
            "vulnerabilities": self.vulnerability_scanner.get_vulnerability_summary(),
            "policies": {
                "total_policies": len(self.policies),
                "strict_policies": len([p for p in self.policies if p.enforcement_level == "strict"]),
            },
        }


class SecurityException(Exception):
    """Security-related exception."""
    pass


# Global security system instance
security_system: Optional[SecurityHardeningSystem] = None