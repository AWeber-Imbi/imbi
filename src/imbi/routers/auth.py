"""
Authentication API endpoints.

Handles login, logout, and user session management.
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from imbi.dependencies import CurrentUser, get_current_user
from imbi.schemas.auth import LoginRequest, LoginResponse, LogoutResponse, WhoAmIResponse
from imbi.services.user import User
from imbi.utils.session import Session, get_session

router = APIRouter(tags=["authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login",
    responses={
        200: {"description": "Login successful"},
        401: {"description": "Invalid credentials"},
    },
)
async def login(
    credentials: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> LoginResponse:
    """
    Authenticate a user and create a session.

    Args:
        credentials: Username and password
        request: FastAPI request
        session: Session instance

    Returns:
        User information and login status

    Raises:
        HTTPException: 401 if credentials are invalid
    """
    config = request.app.state.config

    # Attempt authentication
    user = User(
        config=config,
        username=credentials.username,
        password=credentials.password,
    )

    if not await user.authenticate():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "https://imbi.example.com/errors/unauthorized",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Invalid username or password",
            },
        )

    # Save user data to session
    await session.set_user_data(user.to_dict())

    return LoginResponse(
        username=user.username,
        user_type=user.user_type,
        display_name=user.display_name,
        email_address=user.email_address,
        groups=user.groups,
        permissions=user.permissions,
        message="Login successful",
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    responses={
        200: {"description": "Logout successful"},
    },
)
async def logout(
    session: Annotated[Session, Depends(get_session)],
) -> LogoutResponse:
    """
    Logout the current user and destroy the session.

    Args:
        session: Session instance

    Returns:
        Logout confirmation
    """
    await session.clear()

    return LogoutResponse(message="Logout successful")


@router.get(
    "/whoami",
    response_model=Optional[WhoAmIResponse],
    summary="Get current user",
    responses={
        200: {"description": "Current user information"},
        401: {"description": "Not authenticated"},
    },
)
async def whoami(
    user: CurrentUser,
) -> Optional[WhoAmIResponse]:
    """
    Get information about the currently authenticated user.

    Args:
        user: Current user (optional)

    Returns:
        User information if authenticated, None otherwise
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "https://imbi.example.com/errors/unauthorized",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Not authenticated",
            },
        )

    return WhoAmIResponse(
        username=user.username,
        user_type=user.user_type,
        display_name=user.display_name,
        email_address=user.email_address,
        groups=user.groups,
        permissions=user.permissions,
        authenticated=True,
    )
