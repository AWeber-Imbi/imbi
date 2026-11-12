"""Optional PostHog telemetry for Imbi's own services.

Everything here is a no-op until ``POSTHOG_API_KEY`` is set. The module
configures the global ``posthog`` client, so the ASGI middleware, the
MCP analytics instrumentation, and the AI observability wrapper all
send through one client, which flushes when the process exits.

Environment variables:

- ``POSTHOG_API_KEY``: the project key. Unset turns off every signal.
- ``POSTHOG_HOST``: the ingestion host (default ``DEFAULT_HOST``).
- ``POSTHOG_ERROR_TRACKING``: send exceptions (default ``true``).
- ``POSTHOG_MCP_ANALYTICS``: ``imbi-mcp`` tool calls (default ``false``).
- ``POSTHOG_AI_OBSERVABILITY``: ``imbi-assistant`` LLM calls
  (default ``false``).
- ``POSTHOG_AI_PRIVACY_MODE``: leave prompt and output text out of AI
  events (default ``true``).
"""

import hashlib
import logging
import os
import typing

LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = 'https://us.i.posthog.com'

#: Event properties never sent: the client IP address, and the MCP tool
#: arguments, results, error text, and intent, which can hold project
#: data or secrets.
_DROPPED_PROPERTIES = (
    '$ip',
    '$mcp_parameters',
    '$mcp_response',
    '$mcp_error_message',
    '$mcp_intent',
)

_started = False


def _flag(value: str | None, default: bool) -> bool:
    value = (value or '').strip().lower()
    if not value:
        return default
    return value in {'1', 'true', 'yes', 'on'}


def enabled() -> bool:
    """Return ``True`` when ``POSTHOG_API_KEY`` is set."""
    return bool(os.environ.get('POSTHOG_API_KEY', '').strip())


def error_tracking() -> bool:
    return enabled() and _flag(os.environ.get('POSTHOG_ERROR_TRACKING'), True)


def mcp_analytics() -> bool:
    return enabled() and _flag(os.environ.get('POSTHOG_MCP_ANALYTICS'), False)


def ai_observability() -> bool:
    return enabled() and _flag(
        os.environ.get('POSTHOG_AI_OBSERVABILITY'), False
    )


def distinct_id(subject: str) -> str:
    """Return the PostHog ``distinct_id`` for a token subject.

    A user's token subject is their email, which must not reach
    PostHog. The UI uses the same SHA-256 hex digest, so one person has
    one id in every app. The id is pseudonymous: whoever knows an email
    can compute its id.
    """
    return hashlib.sha256(subject.strip().lower().encode()).hexdigest()


def _scrub(message: dict[str, typing.Any]) -> dict[str, typing.Any]:
    properties = message.get('properties') or {}
    for name in _DROPPED_PROPERTIES:
        properties.pop(name, None)
    return message


def init() -> bool:
    """Configure the global PostHog client from the environment.

    Returns ``False`` (and changes nothing) when the key is not set or
    the ``posthog`` package is not installed. Safe to call twice.
    """
    global _started
    if _started:
        return True
    if not enabled():
        return False
    try:
        import posthog
    except ImportError:  # pragma: no cover
        return False
    posthog.api_key = os.environ['POSTHOG_API_KEY'].strip()
    posthog.host = os.environ.get('POSTHOG_HOST') or DEFAULT_HOST
    posthog.enable_exception_autocapture = error_tracking()
    # Frame locals can hold secret handles (ADR 0022); never send them.
    posthog.capture_exception_code_variables = False
    posthog.privacy_mode = _flag(
        os.environ.get('POSTHOG_AI_PRIVACY_MODE'), True
    )
    posthog.super_properties = {
        'service': os.environ.get('SERVICE', 'unknown')
    }
    posthog.before_send = _scrub
    posthog.default_client = None  # replace any client made before now
    posthog.setup()
    _started = True
    LOGGER.info('PostHog initialized')
    return True


def middleware() -> list[typing.Any]:
    """Start PostHog and return its exception middleware, if any.

    The middleware sends the method, path, user agent, and the URL
    without its query string; never a body, cookies, or headers.
    """
    if not (init() and error_tracking()):
        return []
    from posthog.integrations import asgi
    from starlette.middleware import Middleware

    return [
        Middleware(asgi.PosthogASGIMiddleware, capture_tracing_headers=False)
    ]


def install(app: typing.Any) -> None:
    """Add :func:`middleware` to ``app``.

    Call from the app factory: middleware cannot be added once the app
    has started.
    """
    for item in middleware():
        app.add_middleware(item.cls, *item.args, **item.kwargs)


def capture_exception(exc: BaseException) -> None:
    """Send a handled exception, when error tracking is on."""
    if not (init() and error_tracking()):
        return
    import posthog

    posthog.capture_exception(exc)
