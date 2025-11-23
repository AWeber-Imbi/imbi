"""
Pydantic schemas for authentication endpoints.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Schema for login request."""

    username: str = Field(..., min_length=1, max_length=255, description="Username")
    password: str = Field(..., min_length=1, description="Password")


class LoginResponse(BaseModel):
    """Schema for login response."""

    username: str
    user_type: str
    display_name: str | None = None
    email_address: str | None = None
    groups: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    message: str = "Login successful"


class LogoutResponse(BaseModel):
    """Schema for logout response."""

    message: str = "Logout successful"


class WhoAmIResponse(BaseModel):
    """Schema for /whoami endpoint (current user info)."""

    username: str
    user_type: str
    display_name: str | None = None
    email_address: str | None = None
    groups: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    authenticated: bool = True
