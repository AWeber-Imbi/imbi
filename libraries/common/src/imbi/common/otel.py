"""ASGI middleware that surfaces the OpenTelemetry trace ID on the
response.

When OpenTelemetry instrumentation is active and the request is being
recorded by a valid server span, this middleware adds an HTTP response
header (default ``trace-id``) whose value is the 32-character
lowercase hexadecimal trace ID. Operators and frontend code can use
the returned value to look up the request in the configured tracing
backend (Tempo, Jaeger, Honeycomb, etc.).

The middleware is a no-op when ``opentelemetry-api`` is not installed
or when no valid span context is available, so it is safe to install
unconditionally in services that may or may not be running with
instrumentation enabled.

Example:
    ```python
    from fastapi import FastAPI
    from imbi_common.otel import TraceIdResponseMiddleware

    app = FastAPI()
    app.add_middleware(TraceIdResponseMiddleware)
    ```

    Override the header name (e.g. for services that want a custom
    label exposed via ``Server-Timing`` or a vendor-specific name):

    ```python
    app.add_middleware(
        TraceIdResponseMiddleware, header_name='x-trace-id'
    )
    ```
"""

import typing
from collections import abc

try:
    from opentelemetry import trace as _otel_trace
except ImportError:  # pragma: no cover - optional dependency
    _otel_trace = None  # type: ignore[assignment]

Scope = abc.MutableMapping[str, typing.Any]
Message = abc.MutableMapping[str, typing.Any]
Receive = abc.Callable[[], abc.Awaitable[Message]]
Send = abc.Callable[[Message], abc.Awaitable[None]]
ASGIApp = abc.Callable[[Scope, Receive, Send], abc.Awaitable[None]]

DEFAULT_HEADER_NAME = 'trace-id'


class TraceIdResponseMiddleware:
    """ASGI middleware that adds the active OTEL trace ID to responses.

    Parameters:
        app: The wrapped ASGI application.
        header_name: HTTP header name added to each response when a
            valid trace ID is available. Defaults to ``trace-id``.
            The name is lower-cased and ASCII-encoded before being
            written to the response.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = DEFAULT_HEADER_NAME,
    ) -> None:
        self.app = app
        self._header_name = header_name.lower().encode('ascii')

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope['type'] != 'http' or _otel_trace is None:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message['type'] == 'http.response.start':
                trace_id = current_trace_id()
                if trace_id is not None:
                    existing = message.get('headers') or ()
                    headers: list[tuple[bytes, bytes]] = [
                        (bytes(name), bytes(value)) for name, value in existing
                    ]
                    headers.append(
                        (self._header_name, trace_id.encode('ascii'))
                    )
                    message['headers'] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def current_trace_id() -> str | None:
    """Return the active span's trace ID as a 32-char lowercase hex string.

    Returns ``None`` when ``opentelemetry-api`` is not installed or the
    current span has no valid context (e.g. the request is not being
    recorded). Useful for correlating application logs, audit records,
    or external system calls to an OpenTelemetry trace without
    depending directly on the OTel API.
    """
    if _otel_trace is None:
        return None
    span = _otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, '032x')
