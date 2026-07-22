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
    """Data stored in OAuth state parameter for CSRF protection.

    The identity-plugin flow extends this with optional fields:

    * ``intent`` discriminates ``'login'`` from ``'identity'``.  Login
      flows still create the local user; identity flows persist an
      :class:`imbi_common.models.IdentityConnection` for the actor.
    * ``integration_id`` names the target Integration (or ``None`` for
      the legacy hardcoded login providers).
    * ``code_verifier`` carries the PKCE verifier through the redirect
      so we don't need server-side state for in-flight flows.
    * ``return_to`` is where the UI lands after a successful exchange.
    * ``actor_user_id`` lets a logged-in user begin an identity flow
      without re-authenticating.
    * ``device_code`` is set for OAuth 2.0 device-code flows (e.g.
      AWS IAM IC).  The IdP issues the code at ``StartDeviceAuthorization``
      time and there is no redirect callback to echo it back, so the
      host signs it into the state JWT and pulls it back out on the
      poll endpoint to call ``CreateToken``.
    """

    provider: str
    nonce: str  # Random nonce for CSRF
    redirect_uri: str  # Where to redirect after auth
    timestamp: int  # Unix timestamp for expiry
    intent: typing.Literal['login', 'identity'] = 'login'
    integration_id: str | None = None
    code_verifier: str | None = None
    return_to: str | None = None
    actor_user_id: str | None = None
    device_code: str | None = None


class OAuthCallbackError(pydantic.BaseModel):
    """OAuth callback error response."""

    error: str
    error_description: str | None = None
