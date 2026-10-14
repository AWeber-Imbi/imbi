import http.client
import http.server
import json
import threading
import typing
import unittest
import urllib.request

from imbi.harness import proxy


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: typing.ClassVar[list[str]] = []
    seen_headers: typing.ClassVar[list[set[str]]] = []

    def log_message(self, format: str, *args: typing.Any) -> None:
        pass

    def do_GET(self) -> None:
        self.seen.append(f'GET {self.path}')
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        self.seen.append(f'POST {self.path}')
        self.seen_headers.append({k.lower() for k in self.headers})
        length = int(self.headers['Content-Length'])
        body = json.dumps(
            {
                'path': self.path,
                'headers': {k.lower(): v for k, v in self.headers.items()},
                'body': self.rfile.read(length).decode(),
            }
        ).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Connection', 'X-Upstream-Hop, close')
        self.send_header('X-Upstream-Hop', '1')
        self.send_header('X-Upstream-End', '1')
        self.end_headers()
        self.wfile.write(body)


class ProxyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _Upstream.seen = []
        _Upstream.seen_headers = []
        upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.shutdown)
        host, port = upstream.server_address[:2]
        self.url = proxy.start(f'http://{host!s}:{port}', 'real-key')
        self.host, self.port = self.url.removeprefix('http://').split(':')

    def raw(
        self,
        method: str,
        target: str,
        body: bytes | None = b'{}',
        headers: dict[str, str] | None = None,
    ) -> int:
        """Send a request target as is, with no client normalization."""
        connection = http.client.HTTPConnection(self.host, int(self.port))
        self.addCleanup(connection.close)
        connection.putrequest(method, target, skip_accept_encoding=True)
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        if body is not None and 'Transfer-Encoding' not in (headers or {}):
            connection.putheader('Content-Length', str(len(body)))
        connection.endheaders(body)
        return connection.getresponse().status

    def test_puts_the_real_key_on_the_request(self) -> None:
        request = urllib.request.Request(
            f'{self.url}/v1/messages?beta=true',
            data=b'{"model": "m"}',
            headers={
                'x-api-key': 'placeholder',
                'Authorization': 'Bearer placeholder',
                'anthropic-beta': 'b1',
                'Accept-Encoding': 'gzip',
            },
        )
        with urllib.request.urlopen(request) as response:
            seen = json.loads(response.read())
        self.assertEqual(seen['path'], '/v1/messages?beta=true')
        self.assertEqual(seen['body'], '{"model": "m"}')
        headers = seen['headers']
        self.assertEqual(headers['x-api-key'], 'real-key')
        self.assertEqual(headers['anthropic-beta'], 'b1')
        self.assertNotIn('authorization', headers)
        self.assertNotEqual(headers.get('accept-encoding'), 'gzip')

    def test_forwards_only_the_checked_path_and_query(self) -> None:
        self.assertEqual(self.raw('POST', '/v1/messages?beta=true'), 200)
        self.assertEqual(_Upstream.seen, ['POST /v1/messages?beta=true'])

    def test_body_over_the_limit_is_not_read(self) -> None:
        status = self.raw(
            'POST',
            '/v1/messages',
            None,
            {'Content-Length': str(proxy.MAX_BODY + 1)},
        )
        self.assertEqual(status, 413)
        self.assertEqual(_Upstream.seen, [])

    def test_connection_nominated_headers_are_dropped(self) -> None:
        connection = http.client.HTTPConnection(self.host, int(self.port))
        self.addCleanup(connection.close)
        connection.request(
            'POST',
            '/v1/messages',
            body=b'{}',
            headers={'Connection': 'X-Client-Hop', 'X-Client-Hop': '1'},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        (sent,) = _Upstream.seen_headers
        self.assertNotIn('x-client-hop', sent)
        self.assertIsNone(response.getheader('X-Upstream-Hop'))
        self.assertEqual(response.getheader('X-Upstream-End'), '1')

    def test_count_tokens_goes_upstream(self) -> None:
        self.assertEqual(self.raw('POST', '/v1/messages/count_tokens'), 200)
        self.assertEqual(_Upstream.seen, ['POST /v1/messages/count_tokens'])

    def test_hello_is_answered_locally(self) -> None:
        self.assertEqual(self.raw('HEAD', '/api/hello', None), 200)
        self.assertEqual(_Upstream.seen, [])

    def test_other_requests_never_go_upstream(self) -> None:
        cases = [
            ('GET', '/v1/models', None, {}, 404),
            ('HEAD', '/v1/models', None, {}, 404),
            ('POST', '/v1/files', b'{}', {}, 404),
            ('POST', '/v1/messages/../files', b'{}', {}, 404),
            ('POST', '/v1/messages/%2e%2e/files', b'{}', {}, 404),
            ('POST', 'http://evil.test/v1/messages', b'{}', {}, 404),
            ('POST', '//evil.test/v1/messages', b'{}', {}, 404),
            ('POST', '/v1/messages#/../../v1/files', b'{}', {}, 404),
            ('POST', '/v1/messages?x=1#frag', b'{}', {}, 404),
            ('POST', '/v1/messages?beta=../../v1/files', b'{}', {}, 404),
            ('POST', '/v1/messages?p=/v1/files', b'{}', {}, 404),
            ('POST', '/v1/messages?p=a\\b', b'{}', {}, 404),
            (
                'POST',
                '/v1/messages',
                b'2\r\n{}\r\n0\r\n\r\n',
                {'Transfer-Encoding': 'chunked'},
                411,
            ),
            ('POST', '/v1/messages', None, {}, 411),
            ('DELETE', '/v1/messages', None, {}, 501),
        ]
        for method, target, body, headers, status in cases:
            with self.subTest(method=method, target=target):
                self.assertEqual(
                    self.raw(method, target, body, headers), status
                )
        self.assertEqual(_Upstream.seen, [])
