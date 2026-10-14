"""The loopback model proxy (plan section 6.4), P5a slice.

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
key opens only these routes. Usage metering and the budget come in P5.
"""

import http.client
import http.server
import threading
import typing
import urllib.parse

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
#: The largest request body. The Anthropic Messages API takes requests
#: of up to 32 MB, which images and long contexts can reach; a larger
#: body cannot succeed upstream.
MAX_BODY = 32 * 1024 * 1024
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


def _nominated(values: list[str]) -> frozenset[str]:
    """The header names that a ``Connection`` header nominates as
    hop-by-hop (RFC 9110 section 7.6.1)."""
    return frozenset(
        name.strip().lower()
        for value in values
        for name in value.split(',')
        if name.strip()
    )


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, upstream: str, key: str) -> None:
        super().__init__(('127.0.0.1', 0), _Handler)
        self.upstream = urllib.parse.urlsplit(upstream)
        self.key = key


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
        elif int(self.headers['Content-Length']) > MAX_BODY:
            # No read: the connection closes with the body unread.
            self._refuse(413)
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
        drop = _DROP | _nominated(self.headers.get_all('Connection') or [])
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() not in drop
        }
        headers['x-api-key'] = server.key
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
            hop = _HOP | _nominated(
                response.headers.get_all('Connection') or []
            )
            for name, value in response.getheaders():
                if name.lower() not in hop:
                    self.send_header(name, value)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(b'%x\r\n%s\r\n' % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b'0\r\n\r\n')
        finally:
            upstream.close()


def start(upstream: str, key: str) -> str:
    """Start the proxy in a daemon thread. Return its base URL."""
    server = _Server(upstream, key)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return f'http://{host!s}:{port}'
