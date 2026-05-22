"""Unit tests for the otel middleware."""

import typing
import unittest
from collections import abc
from unittest import mock

from imbi_common import otel


class _RecordingApp:
    """ASGI app that emits a configurable response and records sends."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.start_headers: list[tuple[bytes, bytes]] = [
            (b'content-type', b'text/plain'),
        ]

    async def __call__(
        self,
        scope: abc.MutableMapping[str, typing.Any],
        receive: abc.Callable[[], abc.Awaitable[typing.Any]],
        send: abc.Callable[
            [abc.MutableMapping[str, typing.Any]], abc.Awaitable[None]
        ],
    ) -> None:
        if scope['type'] != 'http':
            return
        await send(
            {
                'type': 'http.response.start',
                'status': self.status,
                'headers': list(self.start_headers),
            }
        )
        await send({'type': 'http.response.body', 'body': b''})


def _http_scope() -> dict[str, typing.Any]:
    return {
        'type': 'http',
        'http_version': '1.1',
        'method': 'GET',
        'path': '/foo',
        'query_string': b'',
        'headers': [],
    }


class _SpanContext:
    def __init__(self, trace_id: int, *, is_valid: bool = True) -> None:
        self.trace_id = trace_id
        self.is_valid = is_valid


class _Span:
    def __init__(self, span_context: _SpanContext) -> None:
        self._ctx = span_context

    def get_span_context(self) -> _SpanContext:
        return self._ctx


async def _noop_receive() -> typing.Any:  # pragma: no cover - never awaited
    raise AssertionError('receive should not be called')


def _start_message(
    captured: list[abc.MutableMapping[str, typing.Any]],
) -> abc.MutableMapping[str, typing.Any]:
    return next(m for m in captured if m['type'] == 'http.response.start')


class TraceIdResponseMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_adds_default_trace_id_header(self) -> None:
        app = _RecordingApp()
        middleware = otel.TraceIdResponseMiddleware(app)
        captured: list[abc.MutableMapping[str, typing.Any]] = []

        async def send(message: abc.MutableMapping[str, typing.Any]) -> None:
            captured.append(message)

        trace_id = 0xDEADBEEFCAFEBABEDEADBEEFCAFEBABE
        with mock.patch.object(otel, '_otel_trace') as mock_trace:
            mock_trace.get_current_span.return_value = _Span(
                _SpanContext(trace_id)
            )
            await middleware(_http_scope(), _noop_receive, send)

        headers = _start_message(captured)['headers']
        expected = format(trace_id, '032x').encode('ascii')
        self.assertIn((b'trace-id', expected), headers)
        self.assertIn((b'content-type', b'text/plain'), headers)

    async def test_custom_header_name_is_lowercased(self) -> None:
        app = _RecordingApp()
        middleware = otel.TraceIdResponseMiddleware(
            app, header_name='X-Trace-ID'
        )
        captured: list[abc.MutableMapping[str, typing.Any]] = []

        async def send(message: abc.MutableMapping[str, typing.Any]) -> None:
            captured.append(message)

        trace_id = 0x00000000000000000000000000000001
        with mock.patch.object(otel, '_otel_trace') as mock_trace:
            mock_trace.get_current_span.return_value = _Span(
                _SpanContext(trace_id)
            )
            await middleware(_http_scope(), _noop_receive, send)

        headers = _start_message(captured)['headers']
        self.assertIn(
            (
                b'x-trace-id',
                b'00000000000000000000000000000001',
            ),
            headers,
        )

    async def test_invalid_span_context_skips_header(self) -> None:
        app = _RecordingApp()
        middleware = otel.TraceIdResponseMiddleware(app)
        captured: list[abc.MutableMapping[str, typing.Any]] = []

        async def send(message: abc.MutableMapping[str, typing.Any]) -> None:
            captured.append(message)

        with mock.patch.object(otel, '_otel_trace') as mock_trace:
            mock_trace.get_current_span.return_value = _Span(
                _SpanContext(0, is_valid=False)
            )
            await middleware(_http_scope(), _noop_receive, send)

        headers = _start_message(captured)['headers']
        self.assertNotIn(b'trace-id', {name for name, _ in headers})

    async def test_otel_unavailable_is_passthrough(self) -> None:
        app = _RecordingApp()
        middleware = otel.TraceIdResponseMiddleware(app)
        captured: list[abc.MutableMapping[str, typing.Any]] = []

        async def send(message: abc.MutableMapping[str, typing.Any]) -> None:
            captured.append(message)

        with mock.patch.object(otel, '_otel_trace', None):
            await middleware(_http_scope(), _noop_receive, send)

        headers = _start_message(captured)['headers']
        self.assertEqual(
            [(b'content-type', b'text/plain')],
            headers,
        )

    async def test_non_http_scope_is_passthrough(self) -> None:
        sent: list[typing.Any] = []
        captured: list[abc.MutableMapping[str, typing.Any]] = []

        async def app(
            scope: abc.MutableMapping[str, typing.Any],
            receive: abc.Callable[[], abc.Awaitable[typing.Any]],
            send: abc.Callable[
                [abc.MutableMapping[str, typing.Any]],
                abc.Awaitable[None],
            ],
        ) -> None:
            sent.append(scope['type'])

        async def send(message: abc.MutableMapping[str, typing.Any]) -> None:
            captured.append(message)

        middleware = otel.TraceIdResponseMiddleware(app)
        await middleware({'type': 'lifespan'}, _noop_receive, send)
        self.assertEqual(['lifespan'], sent)
        self.assertEqual([], captured)

    async def test_current_trace_id_returns_none_when_otel_missing(
        self,
    ) -> None:
        with mock.patch.object(otel, '_otel_trace', None):
            self.assertIsNone(otel.current_trace_id())

    async def test_current_trace_id_returns_hex_string(self) -> None:
        trace_id = 0xCAFEBABEDEADBEEFCAFEBABEDEADBEEF
        with mock.patch.object(otel, '_otel_trace') as mock_trace:
            mock_trace.get_current_span.return_value = _Span(
                _SpanContext(trace_id)
            )
            self.assertEqual(
                'cafebabedeadbeefcafebabedeadbeef',
                otel.current_trace_id(),
            )

    async def test_current_trace_id_returns_none_for_invalid_context(
        self,
    ) -> None:
        with mock.patch.object(otel, '_otel_trace') as mock_trace:
            mock_trace.get_current_span.return_value = _Span(
                _SpanContext(0, is_valid=False)
            )
            self.assertIsNone(otel.current_trace_id())

    async def test_preserves_existing_headers(self) -> None:
        app = _RecordingApp()
        app.start_headers = [
            (b'content-type', b'application/json'),
            (b'x-existing', b'value'),
        ]
        middleware = otel.TraceIdResponseMiddleware(app)
        captured: list[abc.MutableMapping[str, typing.Any]] = []

        async def send(message: abc.MutableMapping[str, typing.Any]) -> None:
            captured.append(message)

        trace_id = 0x0123456789ABCDEF0123456789ABCDEF
        with mock.patch.object(otel, '_otel_trace') as mock_trace:
            mock_trace.get_current_span.return_value = _Span(
                _SpanContext(trace_id)
            )
            await middleware(_http_scope(), _noop_receive, send)

        headers = _start_message(captured)['headers']
        self.assertEqual(
            [
                (b'content-type', b'application/json'),
                (b'x-existing', b'value'),
                (
                    b'trace-id',
                    b'0123456789abcdef0123456789abcdef',
                ),
            ],
            headers,
        )
