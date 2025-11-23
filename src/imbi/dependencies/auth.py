"""
FastAPI dependencies for authentication and authorization.

Replaces Tornado's prepare() lifecycle with dependency injection.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from imbi.services.user import User
from imbi.utils.session import Session, get_session

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    private_token: Annotated[str | None, Header(alias="Private-Token")] = None,
) -> User | None:
    """
    Get the current authenticated user from session or API token.

    This is the base authentication dependency. Returns None if no user is authenticated.

    Args:
        request: FastAPI request
        session: Session instance
        private_token: Optional API token from Private-Token header

    Returns:
        Authenticated User instance or None
    """
    config = request.app.state.config

    # Try token authentication first (if provided)
    if private_token:
        logger.debug("Attempting token authentication")
        user = User(config=config, token=private_token)
        if await user.authenticate():
            logger.info(f"User {user.username} authenticated via token")
            return user
        logger.warning(f"Token authentication failed: {private_token[:8]}...")

    # Try session authentication
    user_data = session.get_user_data()
    if user_data:
        logger.debug(f"Loading user from session: {user_data.get('username')}")
        user = User.from_dict(config=config, data=user_data)

        # Re-authenticate to ensure session is still valid
        if await user.authenticate():
            logger.debug(f"User {user.username} session validated")
            return user

        logger.warning(f"Session authentication failed for {user.username}")
        await session.clear()

    return None


async def require_authentication(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """
    Require an authenticated user.

    Raises 401 if no authenticated user.

    Args:
        user: Optional user from get_current_user

    Returns:
        Authenticated User instance

    Raises:
        HTTPException: 401 if not authenticated
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "https://imbi.example.com/errors/unauthorized",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Authentication required",
            },
        )

    return user


def require_permission(permission: str):
    """
    Create a dependency that requires a specific permission.

    Usage:
        @app.get("/admin/something")
        async def admin_endpoint(
            user: Annotated[User, Depends(require_permission("admin"))]
        ):
            ...

    Args:
        permission: Required permission string

    Returns:
        FastAPI dependency function
    """

    async def permission_dependency(
        user: Annotated[User, Depends(require_authentication)],
    ) -> User:
        """Check if user has required permission."""
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "type": "https://imbi.example.com/errors/forbidden",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": f"Missing required permission: {permission}",
                },
            )

        return user

    return permission_dependency


# Convenience type aliases for common dependencies
CurrentUser = Annotated[User | None, Depends(get_current_user)]
AuthenticatedUser = Annotated[User, Depends(require_authentication)]
AdminUser = Annotated[User, Depends(require_permission("admin"))]
