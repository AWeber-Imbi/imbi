"""The outbound checks of third-party MCP servers (plan P7)."""

import socket
import typing
import unittest
from unittest import mock

import httpx

from imbi.harness import outbound


def _infos(*addresses: str) -> list[typing.Any]:
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 443))
        for a in addresses
    ]


class UrlTestCase(unittest.TestCase):
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


class ResolveTestCase(unittest.IsolatedAsyncioTestCase):
    async def resolve(self, *addresses: str) -> list[str]:
        with mock.patch(
            'asyncio.BaseEventLoop.getaddrinfo',
            mock.AsyncMock(return_value=_infos(*addresses)),
        ):
            return await outbound.resolve('mcp.example.com', 443)

    async def test_global_address(self) -> None:
        self.assertEqual(
            await self.resolve(
                '2600:1f14::1', '93.184.215.14', '2600:1f14::1'
            ),
            ['2600:1f14::1', '93.184.215.14'],
        )

    async def test_any_address_not_global_is_refused(self) -> None:
        for addresses in (
            ('10.0.0.5',),
            ('127.0.0.1',),
            ('169.254.169.254',),
            ('93.184.215.14', '192.168.1.1'),
            ('fd00::1',),
        ):
            with (
                self.subTest(addresses=addresses),
                self.assertRaises(outbound.Refused) as ctx,
            ):
                await self.resolve(*addresses)
            self.assertEqual(ctx.exception.reason, 'address_not_global')

    async def test_literal_addresses(self) -> None:
        self.assertEqual(await outbound.resolve('1.1.1.1', 443), ['1.1.1.1'])
        with self.assertRaises(outbound.Refused):
            await outbound.resolve('10.1.2.3', 443)

    async def test_unknown_host(self) -> None:
        with (
            mock.patch(
                'asyncio.BaseEventLoop.getaddrinfo',
                mock.AsyncMock(side_effect=socket.gaierror('no')),
            ),
            self.assertRaises(outbound.Refused) as ctx,
        ):
            await outbound.resolve('nowhere.example', 443)
        self.assertEqual(ctx.exception.reason, 'host_not_found')


class TransportTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sent: list[httpx.Request] = []
        self.transport = outbound.Transport('https://mcp.example.com/mcp')

        async def inner(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            if request.url.host == '2600:1f14::1':
                raise httpx.ConnectError('no route')
            return httpx.Response(200, json={})

        self.transport.inner = mock.Mock(
            handle_async_request=inner, aclose=mock.AsyncMock()
        )
        resolve = mock.patch.object(
            outbound,
            'resolve',
            mock.AsyncMock(return_value=['2600:1f14::1', '93.184.215.14']),
        )
        resolve.start()
        self.addCleanup(resolve.stop)

    async def test_connects_to_the_checked_address(self) -> None:
        async with httpx.AsyncClient(transport=self.transport) as client:
            await client.post('https://mcp.example.com/mcp')
        # The first checked address does not connect: the next one.
        self.assertEqual(len(self.sent), 2)
        request = self.sent[-1]
        self.assertEqual(request.url.host, '93.184.215.14')
        self.assertEqual(request.headers['host'], 'mcp.example.com')
        self.assertEqual(request.extensions['sni_hostname'], 'mcp.example.com')

    async def test_other_origins_are_refused(self) -> None:
        async with httpx.AsyncClient(transport=self.transport) as client:
            for url in (
                'https://evil.example.com/mcp',
                'https://mcp.example.com:8443/mcp',
                'http://mcp.example.com/mcp',
            ):
                with (
                    self.subTest(url=url),
                    self.assertRaises(outbound.Refused) as ctx,
                ):
                    await client.get(url)
                self.assertEqual(ctx.exception.reason, 'cross_origin_request')
        self.assertEqual(self.sent, [])


class ClientCredentialsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.forms: list[bytes] = []
        self.tokens = iter(['tok-1', 'tok-2'])

        def token_endpoint(request: httpx.Request) -> httpx.Response:
            self.forms.append(request.content)
            return httpx.Response(
                200,
                json={'access_token': next(self.tokens), 'expires_in': 600},
            )

        patcher = mock.patch.object(
            outbound,
            'Transport',
            lambda url: httpx.MockTransport(token_endpoint),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.seen: list[str] = []
        self.auth = outbound.ClientCredentials(
            'https://login.example.com/token',
            'client-1',
            'secret-1',
            'read',
            on_token=self.seen.append,
        )

    async def test_token_is_got_once_and_renewed_on_401(self) -> None:
        statuses = iter([200, 200, 401, 200])
        headers: list[str] = []

        def server(request: httpx.Request) -> httpx.Response:
            headers.append(request.headers['authorization'])
            return httpx.Response(next(statuses))

        async with httpx.AsyncClient(
            auth=self.auth, transport=httpx.MockTransport(server)
        ) as client:
            await client.post('https://mcp.example.com/mcp', content=b'a')
            await client.post('https://mcp.example.com/mcp', content=b'b')
            response = await client.post(
                'https://mcp.example.com/mcp', content=b'c'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            headers,
            ['Bearer tok-1', 'Bearer tok-1', 'Bearer tok-1', 'Bearer tok-2'],
        )
        self.assertEqual(self.seen, ['tok-1', 'tok-2'])
        self.assertIn(b'grant_type=client_credentials', self.forms[0])
        self.assertIn(b'client_secret=secret-1', self.forms[0])
        self.assertIn(b'scope=read', self.forms[0])

    def test_token_url_is_checked(self) -> None:
        with self.assertRaises(outbound.Refused):
            outbound.ClientCredentials('http://login.example.com', 'c', 's')
