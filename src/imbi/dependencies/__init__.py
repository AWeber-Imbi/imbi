"""FastAPI dependencies for Imbi."""

from imbi.dependencies.auth import (
    AdminUser,
    AuthenticatedUser,
    CurrentUser,
    get_current_user,
    require_authentication,
    require_permission,
)

__all__ = [
    "get_current_user",
    "require_authentication",
    "require_permission",
    "CurrentUser",
    "AuthenticatedUser",
    "AdminUser",
]
