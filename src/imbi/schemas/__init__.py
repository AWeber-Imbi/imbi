"""Pydantic schemas for API request/response models."""

from imbi.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    WhoAmIResponse,
)
from imbi.schemas.namespace import (
    NamespaceCreate,
    NamespaceResponse,
    NamespaceUpdate,
)

__all__ = [
    # Auth schemas
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "WhoAmIResponse",
    # Namespace schemas
    "NamespaceCreate",
    "NamespaceResponse",
    "NamespaceUpdate",
]
