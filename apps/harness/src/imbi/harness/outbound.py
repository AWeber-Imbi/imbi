"""The egress proxy environment of the runner and of the executor's
commands (egress proxy plan 5.3), and the outbound checks of the
plugin MCP relay (ADR 0031).

The runner, not the CLI, calls a relayed plugin MCP server, with the
header secrets of the agent's entry. Each connection:

- uses HTTPS, with the certificate checked against the server's host;
- goes only to the origin of the agent's entry. A redirect is followed,
  but a request to another origin is refused before it is sent, so a
  credential goes to its origin only;
- goes through the egress proxy unless ``NO_PROXY`` names the host, as
  the CLI's own requests do.
"""

import asyncio
import ipaddress
import re
import typing
import urllib.parse

import httpx

if typing.TYPE_CHECKING:
    from collections import abc

    from imbi.harness import credential

#: The egress destinations of the chain, from the claim: each has
#: ``cidrs``, ``hostnames``, and ``ports`` (``{port, protocol}``).
type Egress = abc.Sequence[abc.Mapping[str, typing.Any]]

#: The environment variables of the egress proxy (plan 5.3).
PROXY_ENV = frozenset({'HTTPS_PROXY', 'https_proxy', 'NO_PROXY', 'no_proxy'})


def proxy_url(base: str, token: str | None) -> str:
    """``base`` (``http://host:port``) with the proxy token as the
    password of the user ``chain``. No token: no user info."""
    if not token:
        return base
    parts = urllib.parse.urlsplit(base)
    return parts._replace(netloc=f'chain:{token}@{parts.netloc}').geturl()


def proxy_env(
    url: str, *services: str | None, egress: Egress = ()
) -> dict[str, str]:
    """The proxy environment of a command. ``NO_PROXY`` has the
    loopback names, the hosts of ``services`` (imbi-api, imbi-mcp), and
    the CIDRs of the CIDR destinations in ``egress``: a URL with an IP
    literal in them goes direct, through the network policy. curl 7.86+,
    git, and Python requests accept a CIDR in ``no_proxy``."""
    names = ['localhost', '127.0.0.1', '::1']
    names += [
        host
        for service in services
        if service and (host := urllib.parse.urlsplit(service).hostname)
    ]
    names += [
        str(cidr)
        for destination in egress
        for cidr in destination.get('cidrs') or ()
    ]
    no_proxy = ','.join(dict.fromkeys(names))
    return {
        'HTTPS_PROXY': url,
        'https_proxy': url,
        'NO_PROXY': no_proxy,
        'no_proxy': no_proxy,
    }


def proxy_token(env: abc.Mapping[str, str]) -> str | None:
    """The proxy token in the ``HTTPS_PROXY`` of ``env``, to redact."""
    return urllib.parse.urlsplit(env.get('HTTPS_PROXY', '')).password


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


def origin(url: httpx.URL) -> tuple[str, str, int | None]:
    """The scheme, host, and port of ``url``; ``None`` for the scheme's
    default port."""
    return url.scheme, url.host, url.port


def _names(host: str, entry: str) -> bool:
    """Whether one ``NO_PROXY`` entry names ``host``."""
    if entry == '*':
        return True
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(
            entry, strict=False
        )
    except ValueError:
        domain = entry.lstrip('.')
        return host == domain or host.endswith(f'.{domain}')


def bypasses(host: str, no_proxy: str) -> bool:
    """Whether ``NO_PROXY`` names ``host``: the host, a parent domain,
    ``*``, or a CIDR that holds an IP literal host."""
    return any(
        _names(host, entry.strip().lower())
        for entry in no_proxy.split(',')
        if entry.strip()
    )


class Transport(httpx.AsyncBaseTransport):
    """HTTPS to the origin of ``url`` only, through the egress proxy of
    ``proxy_env`` unless its ``NO_PROXY`` names the host."""

    def __init__(self, url: str, proxy_env: abc.Mapping[str, str]) -> None:
        checked = check_url(url)
        self.origin = origin(checked)
        proxy = proxy_env.get('HTTPS_PROXY')
        if bypasses(checked.host, proxy_env.get('NO_PROXY', '')):
            proxy = None
        self.inner = httpx.AsyncHTTPTransport(proxy=proxy or None)

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        if origin(request.url) != self.origin:
            raise Refused('cross_origin_request')
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


_VARIABLE = re.compile(r'\$\{([^}]+)\}')


def fill(template: str, values: abc.Mapping[str, str]) -> str:
    """``template`` with each ``${VAR}`` and ``${VAR:-default}`` filled
    from ``values``. A variable with no value gets its default, else an
    empty value."""

    def value(match: re.Match[str]) -> str:
        name, _, default = match.group(1).partition(':-')
        return values.get(name, default)

    return _VARIABLE.sub(value, template)


class Headers(httpx.Auth):
    """The headers of a plugin MCP server, filled from the current
    secret values on each request, so a renewed secret applies to an
    open session. After a ``401`` the secrets that were sent are renewed
    once, and the request is sent again when one changed.

    Args:
        templates: The server's headers, by name.
        secrets: The secret of each mapped variable, by name.

    """

    requires_request_body = True

    def __init__(
        self,
        templates: abc.Mapping[str, str],
        secrets: abc.Mapping[str, credential.Refresher],
    ) -> None:
        self.templates = templates
        self.secrets = secrets

    def values(self) -> dict[str, str]:
        return {
            name: secret.credential.value
            for name, secret in self.secrets.items()
        }

    def _fill(self, request: httpx.Request, values: dict[str, str]) -> None:
        for name, template in self.templates.items():
            request.headers[name] = fill(template, values)

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> abc.AsyncGenerator[httpx.Request, httpx.Response]:
        sent = self.values()
        self._fill(request, sent)
        response = yield request
        if response.status_code != int(httpx.codes.UNAUTHORIZED):
            return
        # A failed renewal keeps the 401; the refresher retries later.
        await asyncio.gather(
            *(
                secret.renew(sent[name])
                for name, secret in self.secrets.items()
            ),
            return_exceptions=True,
        )
        if (current := self.values()) != sent:
            self._fill(request, current)
            yield request
