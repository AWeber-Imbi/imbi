"""The loopback model proxy (plan section 6.4).

The CLI gets the proxy address and a placeholder key. The proxy puts
the real key on a request and forwards it, with its query, to the
upstream only for ``POST /v1/messages`` and
``POST /v1/messages/count_tokens`` with a ``Content-Length`` body. It
answers ``HEAD /api/hello`` itself. It refuses every other method,
path (no normalization: ``/v1/messages/../files`` is refused), an
absolute-form target, a fragment, a query with ``/``, ``\\``, or
``..``, and a chunked body, with no upstream call. It forwards a target
built from the checked path and query only. The
model's ``Bash`` can reach the proxy too (plan section 6.4), so the
key opens only these routes.

There is one proxy for each task. For a ``POST /v1/messages`` it reads
``usage`` from the response (the ``message_start`` and
``message_delta`` events of a stream, or the JSON body) and gives the
model and the counts to ``meter`` before the response ends, so the
next call sees the new budget. When ``allowed`` returns false (the
budget is spent), it refuses a new call with no upstream call. The
overshoot is one model call (ADR 0020).
"""

import http.client
import http.server
import json
import threading
import typing
import urllib.parse

#: ``meter(model, usage)``: the model id and the ``usage`` fields of one
#: call; ``usage`` is empty when the response had none.
type Meter = typing.Callable[[str, dict[str, typing.Any]], None]
#: The largest JSON response body that the proxy reads usage from.
_JSON_LIMIT = 64 * 1024 * 1024
_SPENT = json.dumps(
    {
        'type': 'error',
        'error': {
            'type': 'invalid_request_error',
            'message': 'The task budget is spent.',
        },
    }
).encode()

#: Request headers that the proxy does not forward. ``Accept-Encoding``
#: is removed so that P5 can read ``usage`` from the response.
_DROP = frozenset(
    {
        'accept-encoding',
        'authorization',
        'connection',
        'content-length',
        'host',
        'keep-alive',
        'proxy-authorization',
        'transfer-encoding',
        'x-api-key',
    }
)
#: The only paths that go upstream, for POST.
_ROUTES = frozenset({'/v1/messages', '/v1/messages/count_tokens'})
_HOP = frozenset(
    {
        'connection',
        'content-length',
        'keep-alive',
        'transfer-encoding',
    }
)


class _Usage:
    """The model and the ``usage`` fields of one response."""

    def __init__(self, request: bytes, stream: bool) -> None:
        self.model = ''
        self.counts: dict[str, typing.Any] = {}
        self.stream = stream
        self.buffer = b''
        try:
            body = json.loads(request)
            self.model = str(body.get('model') or '')
        except (ValueError, AttributeError):
            pass

    def feed(self, chunk: bytes) -> None:
        if len(self.buffer) + len(chunk) > _JSON_LIMIT:
            return
        self.buffer += chunk
        if self.stream:
            *lines, self.buffer = self.buffer.split(b'\n')
            for line in lines:
                if line.startswith(b'data:'):
                    self._event(line[5:])

    def finish(self) -> None:
        if not self.stream:
            self._message(self._json(self.buffer))

    @staticmethod
    def _json(raw: bytes) -> dict[str, typing.Any]:
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]

    def _event(self, raw: bytes) -> None:
        event = self._json(raw)
        if event.get('type') == 'message_start':
            self._message(event.get('message') or {})
        elif event.get('type') == 'message_delta':
            self._add(event.get('usage'))

    def _message(self, message: dict[str, typing.Any]) -> None:
        self.model = str(message.get('model') or self.model)
        self._add(message.get('usage'))

    def _add(self, usage: typing.Any) -> None:
        if isinstance(usage, dict):
            self.counts |= {
                key: value
                for key, value in typing.cast(
                    'dict[str, typing.Any]', usage
                ).items()
                if value is not None
            }


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        upstream: str,
        key: str,
        *,
        litellm: bool,
        meter: Meter | None,
        allowed: typing.Callable[[], bool] | None,
    ) -> None:
        super().__init__(('127.0.0.1', 0), _Handler)
        self.upstream = urllib.parse.urlsplit(upstream)
        self.key = key
        self.litellm = litellm
        self.meter = meter
        self.allowed = allowed


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self) -> None:
        self._refuse(404)

    def do_HEAD(self) -> None:
        if self.path == '/api/hello':
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            self._refuse(404)

    def do_POST(self) -> None:
        # An absolute-form (http://host/...) or a //host/... target has
        # a host part.
        target = urllib.parse.urlsplit(self.path)
        if (
            '#' in self.path
            or target.scheme
            or target.netloc
            or target.path not in _ROUTES
            or any(part in target.query for part in ('/', '\\', '..'))
        ):
            self._refuse(404)
        elif 'Transfer-Encoding' in self.headers or (
            not (self.headers.get('Content-Length') or '').isdigit()
        ):
            self._refuse(411)
        else:
            # Only the checked parts go upstream, never the raw target.
            query = f'?{target.query}' if target.query else ''
            self._forward(target.path + query)

    def _refuse(self, status: int) -> None:
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def log_message(self, format: str, *args: typing.Any) -> None:  # noqa: A002
        """Log nothing: a request line can hold a prompt fragment."""

    def _forward(self, target: str) -> None:
        server = typing.cast('_Server', self.server)
        body = self.rfile.read(int(self.headers['Content-Length']))
        metered = target.split('?')[0] == '/v1/messages'
        if metered and server.allowed is not None and not server.allowed():
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(_SPENT)))
            self.end_headers()
            self.wfile.write(_SPENT)
            return
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() not in _DROP
        }
        headers['x-api-key'] = server.key
        if server.litellm:
            headers['Authorization'] = f'Bearer {server.key}'
        connection_class = (
            http.client.HTTPSConnection
            if server.upstream.scheme == 'https'
            else http.client.HTTPConnection
        )
        upstream = connection_class(server.upstream.netloc, timeout=600)
        try:
            upstream.request(
                self.command,
                server.upstream.path.rstrip('/') + target,
                body=body,
                headers=headers,
            )
            response = upstream.getresponse()
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in _HOP:
                    self.send_header(name, value)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            usage = _Usage(
                body,
                'text/event-stream'
                in (response.getheader('Content-Type') or ''),
            )
            while chunk := response.read1(65536):
                usage.feed(chunk)
                self.wfile.write(b'%x\r\n%s\r\n' % (len(chunk), chunk))
                self.wfile.flush()
            if metered and response.status == http.client.OK and server.meter:
                usage.finish()
                server.meter(usage.model, usage.counts)
            self.wfile.write(b'0\r\n\r\n')
        finally:
            upstream.close()


def start(
    upstream: str,
    key: str,
    *,
    litellm: bool = False,
    meter: Meter | None = None,
    allowed: typing.Callable[[], bool] | None = None,
) -> str:
    """Start the proxy in a daemon thread. Return its base URL.

    ``litellm``: the upstream is a LiteLLM gateway, which also takes
    the key as a bearer token.
    """
    server = _Server(
        upstream, key, litellm=litellm, meter=meter, allowed=allowed
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return f'http://{host!s}:{port}'
