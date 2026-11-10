"""The egress proxy environment of the runner and of the executor's
commands (egress proxy plan 5.3)."""

import typing
import urllib.parse

if typing.TYPE_CHECKING:
    from collections import abc

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
