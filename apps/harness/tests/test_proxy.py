import concurrent.futures
import http.client
import http.server
import json
import threading
import time
import typing
import unittest
import unittest.mock
import urllib.error
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


def _sse(*events: dict[str, typing.Any]) -> bytes:
    return b''.join(
        f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n'.encode()
        for e in events
    )


class _Model(http.server.BaseHTTPRequestHandler):
    """An Anthropic Messages API that streams one reply, or returns JSON."""

    calls: typing.ClassVar[list[dict[str, str]]] = []

    def log_message(self, format: str, *args: typing.Any) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append({k.lower(): v for k, v in self.headers.items()})
        if self.path.startswith('/v1/messages/count_tokens'):
            data, kind = b'{"input_tokens": 3}', 'application/json'
        elif body.get('stream'):
            kind = 'text/event-stream'
            data = _sse(
                {
                    'type': 'message_start',
                    'message': {
                        'model': 'claude-x-20260101',
                        'usage': {
                            'input_tokens': 100,
                            'cache_read_input_tokens': 7,
                            'cache_creation_input_tokens': None,
                            'output_tokens': 1,
                        },
                    },
                },
                {'type': 'content_block_delta', 'delta': {'text': 'hi'}},
                {'type': 'message_delta', 'usage': {'output_tokens': 42}},
                {'type': 'message_stop'},
            )
        else:
            kind = 'application/json'
            data = json.dumps(
                {
                    'model': 'claude-y',
                    'usage': {'input_tokens': 5, 'output_tokens': 6},
                }
            ).encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MeterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _Model.calls = []
        upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Model)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.shutdown)
        host, port = upstream.server_address[:2]
        self.upstream = f'http://{host!s}:{port}'
        self.metered: list[tuple[str, dict[str, typing.Any]]] = []
        self.budget = True

    def start(self, **kwargs: typing.Any) -> str:
        return proxy.start(
            self.upstream,
            'real-key',
            meter=lambda model, usage: self.metered.append((model, usage)),
            allowed=lambda: self.budget,
            **kwargs,
        )

    def post(
        self, url: str, body: dict[str, typing.Any], path: str = '/v1/messages'
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url + path, data=json.dumps(body).encode()
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.read()

    def test_stream_usage(self) -> None:
        status, data = self.post(self.start(), {'model': 'm', 'stream': True})
        self.assertEqual(status, 200)
        self.assertIn(b'message_stop', data)
        self.assertEqual(
            self.metered,
            [
                (
                    'claude-x-20260101',
                    {
                        'input_tokens': 100,
                        'cache_read_input_tokens': 7,
                        'output_tokens': 42,
                    },
                )
            ],
        )

    def test_concurrent_calls_overshoot_by_one_call_at_most(self) -> None:
        def meter(model: str, usage: dict[str, typing.Any]) -> None:
            # A slow usage report that spends the budget.
            time.sleep(0.3)
            self.metered.append((model, usage))
            self.budget = False

        url = proxy.start(
            self.upstream, 'real-key', meter=meter, allowed=lambda: self.budget
        )
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            statuses = sorted(
                pool.map(lambda _: self.post(url, {'model': 'm'})[0], range(2))
            )
        self.assertEqual(statuses, [200, 400])
        self.assertEqual(len(_Model.calls), 1)
        self.assertEqual(len(self.metered), 1)

    def test_json_usage(self) -> None:
        self.post(self.start(), {'model': 'm'})
        self.assertEqual(
            self.metered,
            [('claude-y', {'input_tokens': 5, 'output_tokens': 6})],
        )

    def test_count_tokens_is_not_metered(self) -> None:
        self.budget = False
        status, _ = self.post(
            self.start(), {'model': 'm'}, '/v1/messages/count_tokens'
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.metered, [])

    def test_spent_budget_refuses_with_no_upstream_call(self) -> None:
        self.budget = False
        status, data = self.post(self.start(), {'model': 'm'})
        self.assertEqual(status, 400)
        self.assertIn(b'budget', data)
        self.assertEqual(_Model.calls, [])
        self.assertEqual(self.metered, [])

    def test_litellm_gets_a_bearer_key(self) -> None:
        self.post(self.start(litellm=True), {'model': 'm'})
        (headers,) = _Model.calls
        self.assertEqual(headers['authorization'], 'Bearer real-key')
        self.assertEqual(headers['x-api-key'], 'real-key')

    def test_anthropic_gets_no_bearer(self) -> None:
        self.post(self.start(), {'model': 'm'})
        (headers,) = _Model.calls
        self.assertNotIn('authorization', headers)


class UsageTestCase(unittest.TestCase):
    def test_bad_request_body_and_bad_events(self) -> None:
        usage = proxy._Usage(b'not json', True)
        usage.feed(b'data: {broken\n\ndata: [1]\n\n')
        usage.finish()
        self.assertEqual((usage.model, usage.counts), ('', {}))

    def test_json_body_over_the_limit_is_not_read(self) -> None:
        usage = proxy._Usage(b'{"model": "m"}', False)
        with unittest.mock.patch.object(proxy, '_JSON_LIMIT', 4):
            usage.feed(b'{"usage": {"input_tokens": 1}}')
        usage.finish()
        self.assertEqual((usage.model, usage.counts), ('m', {}))
