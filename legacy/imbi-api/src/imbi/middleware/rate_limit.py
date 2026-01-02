"""Rate limiting middleware using slowapi (Phase 5).

This module provides rate limiting functionality for FastAPI endpoints
using the slowapi library. Rate limits are applied per-user, per-API-key,
or per-IP address depending on the authentication method.
"""

import logging
import typing

import slowapi
from slowapi import errors as slowapi_errors
from slowapi import util as slowapi_util

LOGGER = logging.getLogger(__name__)


def get_rate_limit_key(request: typing.Any) -> str:
    """Extract rate limit key from request.

    The key is determined by priority:
    1. API key ID (if authenticated via API key)
    2. User ID (if authenticated via JWT)
    3. IP address (fallback for unauthenticated requests)

    Args:
        request: FastAPI request object

    Returns:
        Rate limit key string (e.g., 'api_key:ik_abc123',
            'user:johndoe', 'ip:192.168.1.1')

    """
    # Check for auth context (set by get_current_user dependency)
    if hasattr(request.state, 'auth_context'):
        auth = request.state.auth_context
        if hasattr(auth, 'auth_method'):
            if auth.auth_method == 'api_key':
                return f'api_key:{auth.user.email}'
            elif auth.auth_method == 'jwt':
                return f'user:{auth.user.email}'

    # Fallback to IP address
    return f'ip:{slowapi_util.get_remote_address(request)}'


# Initialize limiter with custom key function
limiter = slowapi.Limiter(
    key_func=get_rate_limit_key,
    default_limits=[],  # No default limits, apply per-endpoint
)


def setup_rate_limiting(app: typing.Any) -> None:
    """Setup rate limiting for FastAPI app.

    This function should be called once during application setup to:
    1. Attach the limiter to the app state
    2. Register the rate limit exceeded exception handler

    Args:
        app: FastAPI application instance

    """
    app.state.limiter = limiter
    app.add_exception_handler(
        slowapi_errors.RateLimitExceeded,
        slowapi._rate_limit_exceeded_handler,
    )
    LOGGER.info('Rate limiting initialized with slowapi')
