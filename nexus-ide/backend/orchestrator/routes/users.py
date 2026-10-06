"""Users Routes - API endpoints for multi-user system."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from backend.observability.event_system import get_event_bus
from backend.users.multi_user_system import UserRole, UserStatus, get_multi_user_system

logger = logging.getLogger(__name__)
router = APIRouter()


# Pydantic models for request/response
class UserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"
    first_name: str = ""
    last_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class GroupCreateRequest(BaseModel):
    name: str
    description: str
    is_private: bool = False
    max_members: int = 100


async def get_current_user(authorization: str = Header(None)) -> dict[str, Any]:
    """Get current user from authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    try:
        # Extract token from "Bearer <token>"
        token = authorization.split(" ")[1] if " " in authorization else authorization
        
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        user = await user_system.validate_session(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        return user.to_dict()
        
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed") from e


@router.post("/users/register")
async def register_user(user_data: UserCreateRequest, request: Request) -> dict[str, str]:
    """Register a new user."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Convert role string to enum
        try:
            role_enum = UserRole(user_data.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {user_data.role}") from None
        
        # Create user
        user_id = await user_system.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            role=role_enum,
            first_name=user_data.first_name,
            last_name=user_data.last_name
        )
        
        return {"user_id": user_id, "status": "created"}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to register user: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/users/login")
async def login_user(login_data: LoginRequest,
                    request: Request,
                    ip_address: str = "",
                    user_agent: str = "") -> dict[str, Any]:
    """Login user and create session."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Authenticate
        session = await user_system.authenticate_user(
            username=login_data.username,
            password=login_data.password,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if not session:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        return {
            "session_id": session.session_id,
            "token": session.token,
            "refresh_token": session.refresh_token,
            "expires_at": session.expires_at.isoformat(),
            "user_id": session.user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to login user: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/users/logout")
async def logout_user(session_id: str, request: Request) -> dict[str, str]:
    """Logout user and terminate session."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        success = await user_system.terminate_session(session_id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {"session_id": session_id, "status": "terminated"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to logout user: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/me")
async def get_current_user_info(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Get current user information."""
    return current_user


@router.get("/users")
async def get_users(
    status: str | None = None,
    role: str | None = None,
    limit: int = 100,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, list[dict]]:
    """Get users with optional filtering (admin only)."""
    try:
        # Check permissions
        if current_user["role"] not in ["admin", "moderator"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Convert parameters to enums
        status_enum = None
        if status:
            try:
                status_enum = UserStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from None
        
        role_enum = None
        if role:
            try:
                role_enum = UserRole(role)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid role: {role}") from None
        
        # Get users
        users = await user_system.get_users(
            status=status_enum,
            role=role_enum,
            limit=limit
        )
        
        return {
            "users": [user.to_dict() for user in users],
            "count": len(users)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get users: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Get user by ID."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Check permissions (users can only see their own profile unless admin)
        if current_user["user_id"] != user_id and current_user["role"] not in ["admin", "moderator"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        user = await user_system.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return user.to_dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/groups")
async def get_groups(
    user_id: str | None = None,
    limit: int = 100,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, list[dict]]:
    """Get groups with optional filtering."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Filter by user if not admin
        if current_user["role"] not in ["admin", "moderator"]:
            user_id = current_user["user_id"]
        
        # Get groups
        groups = await user_system.get_groups(user_id=user_id, limit=limit)
        
        return {
            "groups": [group.to_dict() for group in groups],
            "count": len(groups)
        }
        
    except Exception as e:
        logger.error(f"Failed to get groups: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/groups")
async def create_group(
    group_data: GroupCreateRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    """Create a new group."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Create group
        group_id = await user_system.create_group(
            name=group_data.name,
            description=group_data.description,
            created_by=current_user["user_id"],
            is_private=group_data.is_private,
            max_members=group_data.max_members
        )
        
        return {"group_id": group_id, "status": "created"}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to create group: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/groups/{group_id}/join")
async def join_group(
    group_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    """Join a group."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        success = await user_system.join_group(group_id, current_user["user_id"])
        if not success:
            raise HTTPException(status_code=400, detail="Cannot join group")
        
        return {"group_id": group_id, "status": "joined"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to join group {group_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/groups/{group_id}/leave")
async def leave_group(
    group_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    """Leave a group."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        success = await user_system.leave_group(group_id, current_user["user_id"])
        if not success:
            raise HTTPException(status_code=400, detail="Cannot leave group")
        
        return {"group_id": group_id, "status": "left"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to leave group {group_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/activities")
async def get_activities(
    user_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, list[dict]]:
    """Get activity logs with optional filtering."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Filter by user if not admin
        if current_user["role"] not in ["admin", "moderator"]:
            user_id = current_user["user_id"]
        
        # Get activities
        activities = await user_system.get_activity_logs(
            user_id=user_id,
            action=action,
            limit=limit
        )
        
        return {
            "activities": [activity.to_dict() for activity in activities],
            "count": len(activities)
        }
        
    except Exception as e:
        logger.error(f"Failed to get activities: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/stats")
async def get_user_stats(
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Get user system statistics (admin only)."""
    try:
        # Check permissions
        if current_user["role"] not in ["admin"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        return await user_system.get_user_stats()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user stats: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/roles")
async def get_user_roles() -> dict[str, list[str]]:
    """Get available user roles."""
    return {
        "roles": [r.value for r in UserRole],
        "descriptions": {
            "admin": "Full system access and control",
            "moderator": "User and content moderation",
            "developer": "Code execution and deployment",
            "analyst": "Data analysis and reporting",
            "user": "Standard user access",
            "guest": "Read-only access"
        }
    }


@router.get("/users/statuses")
async def get_user_statuses() -> dict[str, list[str]]:
    """Get available user statuses."""
    return {
        "statuses": [s.value for s in UserStatus],
        "descriptions": {
            "active": "User is active and can access the system",
            "inactive": "User is inactive (temporary)",
            "suspended": "User is suspended (temporary)",
            "banned": "User is permanently banned"
        }
    }


@router.post("/users/validate-token")
async def validate_token(
    token: str,
    request: Request
) -> dict[str, Any]:
    """Validate a session token."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        user = await user_system.validate_session(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "valid": True,
            "user": user.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate token: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/dashboard")
async def get_user_dashboard(
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Get user dashboard data."""
    try:
        event_bus = await get_event_bus()
        user_system = await get_multi_user_system(event_bus)
        
        # Get user's groups
        groups = await user_system.get_groups(user_id=current_user["user_id"])
        
        # Get user's recent activities
        activities = await user_system.get_activity_logs(
            user_id=current_user["user_id"],
            limit=10
        )
        
        # Get user stats
        user_stats = await user_system.get_user_stats()
        
        return {
            "user": current_user,
            "groups": [group.to_dict() for group in groups],
            "recent_activities": [activity.to_dict() for activity in activities],
            "stats": {
                "groups_count": len(groups),
                "login_count": current_user["login_count"],
                "last_login": current_user["last_login"],
                "account_age_days": (datetime.now() - datetime.fromisoformat(current_user["created_at"])).days
            },
            "system_stats": {
                "total_users": user_stats["stats"]["total_users"],
                "total_groups": user_stats["stats"]["total_groups"]
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get user dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
