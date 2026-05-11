"""ASGI middleware that replaces uvicorn's built-in access log.

The middleware emits one record per HTTP request on the
``imbi_common.access`` logger. Unlike uvicorn's default access log, it
can suppress records for specific paths *only* when the response was
successful, so high-frequency endpoints (health checks, ``/status``)
stay quiet without hiding failures.
"""

import logging
import typing
from collections import abc

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
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        quiet_paths: abc.Collection[str] = (),
        quiet_status_codes: abc.Container[int] = range(200, 300),
        logger: logging.Logger | None = None,
    ) -> None:
        self.app = app
        self.quiet_paths = frozenset(quiet_paths)
        self.quiet_status_codes = quiet_status_codes
        self.logger = logger or LOGGER

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
        self.logger.info(
            '%s:%s - "%s %s HTTP/%s" %d',
            client[0],
            client[1],
            scope.get('method', '-'),
            full_path,
            scope.get('http_version', '1.1'),
            status,
        )
