"""The loopback model proxy (plan section 6.4), P5a slice.

The CLI gets the proxy address and a placeholder key. The proxy puts
the real key on each request and forwards it, with its path and query,
to the upstream. Usage metering and the budget come in P5.
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
_HOP = frozenset(
    {
        'connection',
        'content-length',
        'keep-alive',
        'transfer-encoding',
    }
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
        self._forward()

    def do_HEAD(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def log_message(self, format: str, *args: typing.Any) -> None:  # noqa: A002
        """Log nothing: a request line can hold a prompt fragment."""

    def _forward(self) -> None:
        server = typing.cast('_Server', self.server)
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() not in _DROP
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
                server.upstream.path.rstrip('/') + self.path,
                body=body,
                headers=headers,
            )
            response = upstream.getresponse()
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in _HOP:
                    self.send_header(name, value)
            if self.command == 'HEAD':
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
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
