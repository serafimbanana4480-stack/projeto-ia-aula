"""Pydantic models for authentication and input validation."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    """Model for user registration request."""
    
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="User password (min 8 characters)",
    )
    full_name: str = Field(
        default="",
        max_length=100,
        description="User full name",
    )
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        # Check for at least one letter and one digit
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one digit")
        return v


class UserLogin(BaseModel):
    """Model for user login request."""
    
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class UserResponse(BaseModel):
    """Model for user response (without sensitive data)."""
    
    id: str
    email: str
    full_name: str = ""
    is_active: bool = True
    created_at: str
    
    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Model for JWT token response."""
    
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class PasswordChange(BaseModel):
    """Model for password change request."""
    
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (min 8 characters)",
    )
    
    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one digit")
        return v