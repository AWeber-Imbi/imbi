"""Rate limiting middleware using slowapi (Phase 5).

This module provides rate limiting functionality for FastAPI endpoints
using the slowapi library. Rate limits are keyed by client IP address.
"""

import logging
import typing

import slowapi
from slowapi import errors as slowapi_errors
from slowapi import util as slowapi_util

LOGGER = logging.getLogger(__name__)


def get_rate_limit_key(request: typing.Any) -> str:
    """Extract rate limit key from request.

    Uses ``slowapi.util.get_remote_address`` which returns
    ``request.client.host``. When deploying behind a reverse proxy,
    ``ProxyHeadersMiddleware`` (configured in ``app.create_app``)
    rewrites ``client.host`` from the trusted ``X-Forwarded-For``
    chain before this function runs, so the key reflects the real
    client rather than the proxy address.
    """
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
