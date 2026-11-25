"""The egress proxy environment (egress proxy plan 5.3) and the outbound
checks of the plugin MCP relay (ADR 0031)."""

import asyncio
import base64
import datetime
import socket
import unittest
from unittest import mock

import httpx

from imbi.harness import credential, outbound, proxy

PROXY = 'http://chain:tok.en@proxy.example:3128'


class ProxyHelpersTestCase(unittest.TestCase):
    """The egress proxy environment (egress proxy plan 5.3)."""

    def test_proxy_url(self) -> None:
        self.assertEqual(
            outbound.proxy_url('http://proxy.example:3128', 'tok.en'), PROXY
        )
        self.assertEqual(
            outbound.proxy_url('http://proxy.example:3128', None),
            'http://proxy.example:3128',
        )

    def test_no_proxy_has_the_configured_services(self) -> None:
        env = outbound.proxy_env(
            PROXY,
            'http://imbi-api.imbi.svc:8000/api',
            'http://imbi-mcp.imbi.svc:8001/mcp',
            None,
        )
        self.assertEqual(env['HTTPS_PROXY'], PROXY)
        self.assertEqual(env['https_proxy'], PROXY)
        self.assertEqual(env['NO_PROXY'], env['no_proxy'])
        excluded = env['NO_PROXY'].split(',')
        # The API, the MCP server, the local model proxy (127.0.0.1),
        # and the IPv6 loopback do not go through the proxy.
        for host in (
            'imbi-api.imbi.svc',
            'imbi-mcp.imbi.svc',
            '127.0.0.1',
            '::1',
            'localhost',
        ):
            with self.subTest(host=host):
                self.assertIn(host, excluded)
        self.assertEqual(outbound.proxy_token(env), 'tok.en')
        self.assertIsNone(outbound.proxy_token({}))


class CheckUrlTestCase(unittest.TestCase):
    def test_only_https_with_a_host(self) -> None:
        self.assertEqual(
            outbound.check_url('https://mcp.example.com/mcp').host,
            'mcp.example.com',
        )
        for url, reason in (
            ('http://mcp.example.com/mcp', 'url_not_https'),
            ('ftp://mcp.example.com', 'url_not_https'),
            ('https://user:pw@mcp.example.com', 'url_not_valid'),
            ('https:///mcp', 'url_not_valid'),
        ):
            with (
                self.subTest(url=url),
                self.assertRaises(outbound.Refused) as ctx,
            ):
                outbound.check_url(url)
            self.assertEqual(ctx.exception.reason, reason)


class BypassesTestCase(unittest.TestCase):
    def test_no_proxy_entries(self) -> None:
        no_proxy = 'localhost,.svc.cluster.local,example.org,10.0.0.0/8'
        for host, expected in (
            ('localhost', True),
            ('imbi.svc.cluster.local', True),
            ('example.org', True),
            ('mcp.example.org', True),
            ('10.1.2.3', True),
            ('notexample.org', False),
            ('mcp.example.com', False),
            ('11.1.2.3', False),
        ):
            with self.subTest(host=host):
                self.assertEqual(outbound.bypasses(host, no_proxy), expected)
        self.assertTrue(outbound.bypasses('anything.example', ' * '))
        self.assertFalse(outbound.bypasses('mcp.example.com', ''))


class TransportTestCase(unittest.IsolatedAsyncioTestCase):
    """The origin pin, with the network replaced by a mock."""

    def setUp(self) -> None:
        self.sent: list[httpx.URL] = []
        self.transport = outbound.Transport('https://mcp.example.com/mcp', {})

        def network(request: httpx.Request) -> httpx.Response:
            self.sent.append(request.url)
            target = {
                '/same': 'https://mcp.example.com/moved',
                '/other': 'https://evil.example.com/mcp',
                '/port': 'https://mcp.example.com:8443/mcp',
                '/plain': 'http://mcp.example.com/mcp',
            }.get(request.url.path)
            if target is None:
                return httpx.Response(200, json={})
            return httpx.Response(302, headers={'Location': target})

        self.transport.inner = httpx.MockTransport(network)  # type: ignore[assignment]

    async def get(self, path: str) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=self.transport, follow_redirects=True
        ) as client:
            return await client.get(f'https://mcp.example.com{path}')

    async def test_redirect_to_the_same_origin_is_followed(self) -> None:
        response = await self.get('/same')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([url.path for url in self.sent], ['/same', '/moved'])

    async def test_redirect_to_another_origin_is_refused(self) -> None:
        for path in ('/other', '/port', '/plain'):
            with (
                self.subTest(path=path),
                self.assertRaises(outbound.Refused) as ctx,
            ):
                await self.get(path)
            self.assertEqual(ctx.exception.reason, 'cross_origin_request')
        self.assertEqual(
            [url.host for url in self.sent], ['mcp.example.com'] * 3
        )

    def test_the_url_is_checked(self) -> None:
        with self.assertRaises(outbound.Refused):
            outbound.Transport('http://mcp.example.com/mcp', {})


class ProxyRouteTestCase(unittest.IsolatedAsyncioTestCase):
    """Like the CLI, the relay goes through the egress proxy unless
    ``NO_PROXY`` names the host."""

    async def asyncSetUp(self) -> None:
        self.heads: list[bytes] = []

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            self.heads.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(
                b'HTTP/1.1 403 Forbidden\r\ncontent-length: 0\r\n\r\n'
            )
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(handle, '127.0.0.1', 0)
        self.addAsyncCleanup(self.server.wait_closed)
        self.addCleanup(self.server.close)
        port = self.server.sockets[0].getsockname()[1]
        self.proxy = f'http://chain:tok.en@127.0.0.1:{port}'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.closed = sock.getsockname()[1]

    async def post(self, no_proxy: str) -> None:
        url = f'https://127.0.0.1:{self.closed}/mcp'
        transport = outbound.Transport(
            url, {'HTTPS_PROXY': self.proxy, 'NO_PROXY': no_proxy}
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post(url)

    async def test_through_the_proxy(self) -> None:
        with self.assertRaises(httpx.ProxyError):
            await self.post('10.0.0.0/8')
        head = self.heads[0].decode()
        self.assertTrue(
            head.startswith(f'CONNECT 127.0.0.1:{self.closed} HTTP/1.1'),
            head,
        )
        self.assertIn(
            'Basic ' + base64.b64encode(b'chain:tok.en').decode(), head
        )

    async def test_no_proxy_goes_direct(self) -> None:
        with self.assertRaises(httpx.ConnectError):
            await self.post('127.0.0.0/8')
        self.assertEqual(self.heads, [])


def _refresher(*values: str, expires: bool = True) -> credential.Refresher:
    """A refresher whose fetches return ``values`` in order."""
    expiry = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
    fetch = mock.AsyncMock(
        side_effect=[
            proxy.Credential(value, expiry if expires else None)
            for value in values
        ]
    )
    return credential.Refresher(fetch, 'test')


class HeadersTestCase(unittest.IsolatedAsyncioTestCase):
    async def send(
        self,
        auth: outbound.Headers,
        statuses: list[int],
    ) -> tuple[httpx.Response, list[httpx.Headers]]:
        seen: list[httpx.Headers] = []

        def network(request: httpx.Request) -> httpx.Response:
            seen.append(httpx.Headers(request.headers))
            return httpx.Response(statuses[len(seen) - 1])

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(network), auth=auth
        ) as client:
            response = await client.post('https://mcp.example.com/mcp')
        return response, seen

    async def test_templates_are_filled(self) -> None:
        token = _refresher('t1')
        await token.start()
        token.stop()
        auth = outbound.Headers(
            {
                'Authorization': 'Bearer ${TOKEN}',
                'X-Region': '${REGION:-us-east-1}',
                'X-Team': '${TEAM}',
            },
            {'TOKEN': token},
        )
        _, (headers,) = await self.send(auth, [200])
        self.assertEqual(headers['authorization'], 'Bearer t1')
        self.assertEqual(headers['x-region'], 'us-east-1')
        self.assertEqual(headers['x-team'], '')

    async def test_a_renewed_secret_applies_to_the_next_request(
        self,
    ) -> None:
        token = _refresher('t1', 't2')
        await token.start()
        token.stop()
        auth = outbound.Headers({'Authorization': 'Bearer ${T}'}, {'T': token})
        await token.renew()
        _, (headers,) = await self.send(auth, [200])
        self.assertEqual(headers['authorization'], 'Bearer t2')

    async def test_a_401_renews_once_and_sends_again(self) -> None:
        token = _refresher('t1', 't2')
        await token.start()
        token.stop()
        auth = outbound.Headers({'Authorization': 'Bearer ${T}'}, {'T': token})
        response, seen = await self.send(auth, [401, 401])
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            [h['authorization'] for h in seen], ['Bearer t1', 'Bearer t2']
        )

    async def test_a_static_secret_is_not_sent_again_after_a_401(
        self,
    ) -> None:
        token = _refresher('static', expires=False)
        await token.start()
        auth = outbound.Headers({'X-Api-Key': '${KEY}'}, {'KEY': token})
        response, seen = await self.send(auth, [401])
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(seen), 1)
