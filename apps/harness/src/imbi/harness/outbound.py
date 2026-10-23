"""Outbound checks for third-party MCP servers (harness plan P7).

The runner, not ``agent``, makes every call to a third-party MCP server
and to its OAuth token URL. The URLs come from the admin's server
configuration; the model cannot choose one. Each connection:

- uses HTTPS, with the certificate checked against the configured host;
- goes only to the configured origin. A request to another origin is
  refused, so a credential goes to its origin only (the clients also
  follow no redirects);
- connects only to an allowed address: a global address, or an
  address in a CIDR of an egress destination of the chain that has the
  port on TCP (the same list as the pod's network policy). Loopback,
  link-local (IMDS), multicast, and unspecified addresses are never
  allowed. The runner resolves the host, refuses it when any address
  is not allowed, and connects to the addresses that it checked, in
  order, so a second DNS answer cannot change them.
"""

import asyncio
import ipaddress
import socket
import time
import typing

import httpx

if typing.TYPE_CHECKING:
    from collections import abc

#: The egress destinations of the chain, from the claim: each has
#: ``cidrs`` and ``ports`` (``{port, protocol}``).
type Egress = abc.Sequence[abc.Mapping[str, typing.Any]]


class Refused(httpx.TransportError):
    """An outbound check refused the request. ``reason`` is a safe
    code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def check_url(url: str) -> httpx.URL:
    """The URL, when it is an HTTPS URL with a host and no user info.

    Raises:
        Refused: ``url_not_https`` or ``url_not_valid``.

    """
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as err:
        raise Refused('url_not_valid') from err
    if parsed.scheme != 'https':
        raise Refused('url_not_https')
    if not parsed.host or parsed.userinfo:
        raise Refused('url_not_valid')
    return parsed


def _allowed(address: str, port: int, egress: Egress) -> bool:
    try:
        ip = ipaddress.ip_address(address.partition('%')[0])
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    if ip.is_unspecified:
        return False
    if ip.is_global:
        return True
    return any(
        any(
            int(p['port']) == port and p['protocol'] == 'TCP'
            for p in destination['ports']
        )
        and any(
            ip in ipaddress.ip_network(cidr, strict=False)
            for cidr in destination['cidrs']
        )
        for destination in egress
    )


async def resolve(host: str, port: int, egress: Egress = ()) -> list[str]:
    """The addresses of ``host``, in the system's order of preference,
    when all of them are allowed.

    Raises:
        Refused: ``address_not_allowed`` when any address of the host is
            not allowed, or ``host_not_found``.

    """
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _allowed(host, port, egress):
            raise Refused('address_not_allowed')
        return [host]
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError as err:
        raise Refused('host_not_found') from err
    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise Refused('host_not_found')
    if not all(_allowed(address, port, egress) for address in addresses):
        raise Refused('address_not_allowed')
    return addresses


class Transport(httpx.AsyncBaseTransport):
    """HTTPS to one origin, connected to a checked allowed address."""

    def __init__(self, url: str, egress: Egress = ()) -> None:
        origin = check_url(url)
        self.origin = (origin.scheme, origin.host, origin.port or 443)
        self.egress = egress
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        url = request.url
        if (url.scheme, url.host, url.port or 443) != self.origin:
            raise Refused('cross_origin_request')
        addresses = await resolve(url.host, self.origin[2], self.egress)
        # The Host header keeps the name; TLS checks the certificate
        # against the name too (SNI).
        request.extensions = {**request.extensions, 'sni_hostname': url.host}
        for address in addresses[:-1]:
            request.url = url.copy_with(host=address)
            try:
                return await self.inner.handle_async_request(request)
            except httpx.ConnectError:
                # No byte of the request was sent: try the next one.
                continue
        request.url = url.copy_with(host=addresses[-1])
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


class Header(httpx.Auth):
    """A static credential in one header."""

    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value

    def auth_flow(
        self, request: httpx.Request
    ) -> abc.Generator[httpx.Request, httpx.Response]:
        request.headers[self.name] = self.value
        yield request


class ClientCredentials(httpx.Auth):
    """An OAuth client-credentials access token, got by the runner and
    kept in its memory. The token URL has the same outbound checks."""

    #: A 401 sends the request again with a new token.
    requires_request_body = True

    def __init__(  # noqa: PLR0913
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None = None,
        *,
        on_token: abc.Callable[[str], None] = lambda _token: None,
        egress: Egress = (),
    ) -> None:
        check_url(token_url)
        self.egress = egress
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        #: Called with each new access token (for the redactor).
        self.on_token = on_token
        self.token: str | None = None
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def _fetch(self) -> str:
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }
        if self.scope:
            data['scope'] = self.scope
        async with httpx.AsyncClient(
            transport=Transport(self.token_url, self.egress),
            follow_redirects=False,
            timeout=30,
        ) as client:
            response = await client.post(self.token_url, data=data)
        response.raise_for_status()
        try:
            body = response.json()
            token = str(body['access_token'])
            lifetime = int(body.get('expires_in', 3600))
        except (ValueError, KeyError, TypeError) as err:
            raise Refused('token_response_not_valid') from err
        self.token = token
        self.on_token(token)
        # A minute early, so a token never ends during a call.
        self.expires = time.monotonic() + lifetime - 60
        return token

    async def _current(self, *, renew: bool = False) -> str:
        async with self.lock:
            if renew or self.token is None or time.monotonic() >= self.expires:
                return await self._fetch()
            return self.token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> abc.AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers['Authorization'] = f'Bearer {await self._current()}'
        response = yield request
        if response.status_code == int(httpx.codes.UNAUTHORIZED):
            token = await self._current(renew=True)
            request.headers['Authorization'] = f'Bearer {token}'
            yield request
