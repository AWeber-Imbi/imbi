"""ASGI middleware that replaces uvicorn's built-in access log.

The middleware emits one record per HTTP request on the
``imbi_common.access`` logger. Unlike uvicorn's default access log, it
can suppress records for specific paths *only* when the response was
successful, so high-frequency endpoints (health checks, ``/status``)
stay quiet without hiding failures.

The authenticated principal is extracted from the ``Authorization``
header and rendered in the NCSA-style ``authuser`` slot of the log
line. JWTs are decoded and signature-verified; valid tokens log the
local part of the ``sub`` claim (or the full subject if it is not an
email). API keys (``ik_<id>_<secret>``) log the ``ik_<id>`` prefix
only. Anything else logs ``-``.

Downstream handlers can attach extra context to a request's log line
by populating ``request.state.imbi_common_access_log`` (equivalently
``scope['state']['imbi_common_access_log']``) with a mapping. Each
entry is rendered as ``key:value`` in a space-separated list wrapped
in parentheses after the status code, e.g.
``... 200 (event_type:x selected:False)``.

When OpenTelemetry instrumentation is active and a valid server span
is recording the request, the active trace ID is prepended to the
context suffix as ``trace_id:<32-char hex>``. This requires no
configuration beyond installing ``imbi-common[otel]`` and wiring up
the SDK; it is suppressed by passing ``include_trace_context=False``
to the middleware constructor.
"""

import logging
import typing
from collections import abc

import jwt

from imbi_common import otel, settings
from imbi_common.auth import core

LOGGER = logging.getLogger('imbi_common.access')

Scope = abc.MutableMapping[str, typing.Any]
Message = abc.MutableMapping[str, typing.Any]
Receive = abc.Callable[[], abc.Awaitable[Message]]
Send = abc.Callable[[Message], abc.Awaitable[None]]
ASGIApp = abc.Callable[[Scope, Receive, Send], abc.Awaitable[None]]


class AccessLogMiddleware:
    """ASGI middleware that logs each HTTP request.

    Parameters:
        app: The wrapped ASGI application.
        quiet_paths: Request paths whose successful responses should
            not be logged. Matched exactly against ``scope['path']``.
        quiet_status_codes: Status codes considered "successful" for
            the purpose of silencing ``quiet_paths``. Defaults to
            ``range(200, 300)`` so 4xx/5xx on a quiet path is still
            logged (e.g. ``GET /status`` returning 404 because the
            endpoint isn't wired up).
        logger: Logger to emit records on. Defaults to
            ``imbi_common.access``.
        include_principal: When ``True`` (the default), inspect the
            ``Authorization`` header on each request and render the
            authenticated principal in the log line. Set to ``False``
            to suppress the lookup for services that don't issue JWTs
            or API keys.
        include_trace_context: When ``True`` (the default), prepend
            ``trace_id:<hex>`` to the log line's context suffix when
            an OpenTelemetry server span is recording the request.
            Has no effect when ``opentelemetry-api`` is not installed
            or no valid span is active.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        quiet_paths: abc.Collection[str] = (),
        quiet_status_codes: abc.Container[int] = range(200, 300),
        logger: logging.Logger | None = None,
        include_principal: bool = True,
        include_trace_context: bool = True,
    ) -> None:
        self.app = app
        self.quiet_paths = frozenset(quiet_paths)
        self.quiet_status_codes = quiet_status_codes
        self.logger = logger or LOGGER
        self.include_principal = include_principal
        self.include_trace_context = include_trace_context

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message['type'] == 'http.response.start':
                status = int(message.get('status', 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            self._emit(scope, status)

    def _emit(self, scope: Scope, status: int) -> None:
        path = scope.get('path', '')
        if path in self.quiet_paths and status in self.quiet_status_codes:
            return

        client = scope.get('client') or ('-', 0)
        query = scope.get('query_string') or b''
        full_path = path
        if query:
            full_path = f'{path}?{query.decode("latin-1")}'
        principal = '-'
        if self.include_principal:
            try:
                principal = _principal_from_scope(scope)
            except Exception:  # noqa: BLE001 - defensive: never fail logging
                principal = '-'
        context: list[tuple[object, object]] = []
        if self.include_trace_context:
            trace_id = otel.current_trace_id()
            if trace_id is not None:
                context.append(('trace_id', trace_id))
        state = scope.get('state')
        if isinstance(state, abc.Mapping):
            extra = state.get('imbi_common_access_log')
            if isinstance(extra, abc.Mapping):
                context.extend(extra.items())
        suffix = ''
        if context:
            rendered = ' '.join(
                f'{_sanitize_log_field(k)}:{_sanitize_log_field(v)}'
                for k, v in context
            )
            suffix = f' ({rendered})'
        self.logger.info(
            '%s:%s - %s "%s %s HTTP/%s" %d%s',
            client[0],
            client[1],
            principal,
            scope.get('method', '-'),
            full_path,
            scope.get('http_version', '1.1'),
            status,
            suffix,
        )


def _principal_from_scope(scope: Scope) -> str:
    """Return the authenticated principal label for an ASGI request.

    Returns ``-`` when no usable ``Authorization: Bearer`` credential
    is present, the JWT signature fails to verify, or the credential
    is otherwise malformed. JWT verification reuses the shared
    ``imbi_common.auth.core.verify_token`` path; auth settings are
    fetched lazily so middleware import doesn't force-load them.
    """
    headers = scope.get('headers') or ()
    auth_value: bytes | None = None
    for name, value in headers:
        if name.lower() == b'authorization':
            auth_value = value
            break
    if auth_value is None:
        return '-'
    auth = auth_value.decode('latin-1')
    scheme, _, token = auth.partition(' ')
    if scheme.lower() != 'bearer':
        return '-'
    token = token.strip()
    if not token:
        return '-'
    if token.startswith('ik_'):
        # API key: ``ik_<key_id>_<secret>`` — log the key id only.
        # Verifying the secret would require a database lookup, so we
        # accept the (cheap) tradeoff of logging the claimed key id
        # before the auth dependency confirms it. The request's status
        # reflects whether validation actually succeeded.
        parts = token.split('_', 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return f'ik_{parts[1]}'
        return '-'
    try:
        claims = core.verify_token(token, settings.get_auth_settings())
    except jwt.PyJWTError:
        return '-'
    subject = claims.get('sub')
    if not isinstance(subject, str) or not subject:
        return '-'
    local, sep, _ = subject.partition('@')
    return local if sep else subject


def _sanitize_log_field(value: object) -> str:
    """Render ``value`` for the access-log suffix.

    Control characters (``\\r``, ``\\n``) are escaped to literal
    backslash sequences so handler-supplied context cannot forge new
    log lines via embedded newlines.
    """
    return str(value).replace('\r', r'\r').replace('\n', r'\n')
