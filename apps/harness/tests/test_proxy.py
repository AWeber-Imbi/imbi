import http.server
import json
import threading
import typing
import unittest
import urllib.request

from imbi.harness import proxy


class _Upstream(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:
        pass

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_POST(self) -> None:
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
        self.end_headers()
        self.wfile.write(body)


class ProxyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.shutdown)
        host, port = upstream.server_address[:2]
        self.url = proxy.start(f'http://{host!s}:{port}', 'real-key')

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

    def test_head(self) -> None:
        request = urllib.request.Request(
            f'{self.url}/api/hello', method='HEAD'
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
