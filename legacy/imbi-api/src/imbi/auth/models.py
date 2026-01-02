"""Request and response models for authentication endpoints."""

import typing

import pydantic


class LoginRequest(pydantic.BaseModel):
    """Login request with email and password."""

    email: pydantic.EmailStr
    password: str


class TokenResponse(pydantic.BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = 'bearer'
    expires_in: int


class TokenRefreshRequest(pydantic.BaseModel):
    """Request to refresh an access token."""

    refresh_token: str


class AuthProvider(pydantic.BaseModel):
    """Authentication provider configuration for UI."""

    id: str  # 'google', 'github', 'oidc', 'local'
    type: typing.Literal['oauth', 'password']
    name: str  # Display name
    enabled: bool
    auth_url: str | None = None  # URL to initiate auth (for OAuth)
    icon: str | None = None  # Icon identifier for UI


class AuthProvidersResponse(pydantic.BaseModel):
    """List of available authentication providers."""

    providers: list[AuthProvider]
    default_redirect: str = '/dashboard'


class OAuthStateData(pydantic.BaseModel):
    """Data stored in OAuth state parameter for CSRF protection."""

    provider: str
    nonce: str  # Random nonce for CSRF
    redirect_uri: str  # Where to redirect after auth
    timestamp: int  # Unix timestamp for expiry


class OAuthCallbackError(pydantic.BaseModel):
    """OAuth callback error response."""

    error: str
    error_description: str | None = None
