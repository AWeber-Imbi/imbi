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
            self.assertEqual(ctx.exception.reason, 'address_not_allowed')

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


DB = {
    'slug': 'db',
    'generation': 1,
    'cidrs': ['10.1.0.0/16'],
    'ports': [{'port': 443, 'protocol': 'TCP'}],
}
DNS = {
    'slug': 'dns',
    'generation': 1,
    'cidrs': ['10.2.0.0/16'],
    'ports': [{'port': 443, 'protocol': 'UDP'}],
}
IMDS = {
    'slug': 'imds',
    'generation': 1,
    'cidrs': ['169.254.0.0/16', '127.0.0.0/8'],
    'ports': [{'port': 443, 'protocol': 'TCP'}],
}


class EgressTestCase(unittest.IsolatedAsyncioTestCase):
    """The chain's egress destinations (PRD 5.8)."""

    async def resolve(
        self, *addresses: str, egress: outbound.Egress, port: int = 443
    ) -> list[str]:
        with mock.patch(
            'asyncio.BaseEventLoop.getaddrinfo',
            mock.AsyncMock(return_value=_infos(*addresses)),
        ):
            return await outbound.resolve('mcp.internal', port, egress)

    async def test_allowed_cidr_and_tcp_port(self) -> None:
        self.assertEqual(
            await self.resolve('10.1.2.3', egress=[DB]), ['10.1.2.3']
        )
        self.assertEqual(
            await outbound.resolve('10.1.2.3', 443, [DB]), ['10.1.2.3']
        )

    async def test_refused(self) -> None:
        for addresses, egress, port in (
            # The CIDR, but another port.
            (('10.1.2.3',), [DB], 8443),
            # A UDP-only destination on 443.
            (('10.2.0.1',), [DNS], 443),
            # A private address on no list.
            (('10.9.0.1',), [DB], 443),
            # IMDS and loopback, also when listed.
            (('169.254.169.254',), [IMDS], 443),
            (('127.0.0.1',), [IMDS], 443),
            # No destinations.
            (('10.1.2.3',), [], 443),
            # One allowed and one unlisted address.
            (('10.1.2.3', '10.9.0.1'), [DB], 443),
        ):
            with (
                self.subTest(addresses=addresses, port=port),
                self.assertRaises(outbound.Refused) as ctx,
            ):
                await self.resolve(*addresses, egress=egress, port=port)
            self.assertEqual(ctx.exception.reason, 'address_not_allowed')

    async def test_global_address_needs_no_destination(self) -> None:
        self.assertEqual(
            await self.resolve('93.184.215.14', egress=[]), ['93.184.215.14']
        )


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

        self.transports: list[tuple[str, outbound.Egress]] = []

        def transport(
            url: str, egress: outbound.Egress = ()
        ) -> httpx.MockTransport:
            self.transports.append((url, egress))
            return httpx.MockTransport(token_endpoint)

        patcher = mock.patch.object(outbound, 'Transport', transport)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.seen: list[str] = []
        self.auth = outbound.ClientCredentials(
            'https://login.example.com/token',
            'client-1',
            'secret-1',
            'read',
            on_token=self.seen.append,
            egress=[DB],
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
        # The token URL has the chain's destinations too.
        self.assertEqual(
            self.transports[0], ('https://login.example.com/token', [DB])
        )

    def test_token_url_is_checked(self) -> None:
        with self.assertRaises(outbound.Refused):
            outbound.ClientCredentials('http://login.example.com', 'c', 's')


class TwoDestinationsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_and_token_url_on_two_destinations(self) -> None:
        """The MCP origin and the OAuth token URL are on two internal
        destinations of the chain: both connect."""
        auth_net = {**DB, 'slug': 'auth', 'cidrs': ['10.3.0.0/16']}
        egress = [DB, auth_net]
        sent: list[str] = []

        async def inner(request: httpx.Request) -> httpx.Response:
            sent.append(str(request.url.host))
            if request.url.path == '/token':
                return httpx.Response(200, json={'access_token': 'tok'})
            return httpx.Response(200, json={})

        hosts = {'mcp.internal': '10.1.0.5', 'login.internal': '10.3.0.5'}

        getaddrinfo = mock.AsyncMock(
            side_effect=lambda host, _port, **_: _infos(hosts[host])
        )
        real = outbound.Transport

        def transport(
            url: str, egress: outbound.Egress = ()
        ) -> outbound.Transport:
            made = real(url, egress)
            made.inner = mock.Mock(
                handle_async_request=inner, aclose=mock.AsyncMock()
            )
            return made

        with (
            mock.patch('asyncio.BaseEventLoop.getaddrinfo', getaddrinfo),
            mock.patch.object(outbound, 'Transport', transport),
        ):
            auth = outbound.ClientCredentials(
                'https://login.internal/token', 'c', 's', egress=egress
            )
            async with httpx.AsyncClient(
                auth=auth,
                transport=transport('https://mcp.internal/mcp', egress),
            ) as client:
                response = await client.post('https://mcp.internal/mcp')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sent, ['10.3.0.5', '10.1.0.5'])
