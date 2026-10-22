"""Persistence and validation for OAuth2 client registrations.

Clients that self-register via :rfc:`7591` dynamic client registration
are stored as ``OAuthClient`` graph nodes. The Authorization Server
endpoints (``/auth/register``, ``/auth/authorize``, ``/auth/token``) use
the helpers here to create clients and look them up when validating an
authorization request or token exchange.
"""

import logging
from urllib import parse as urlparse

import nanoid

from imbi.api import models
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

# Native clients (e.g. desktop MCP apps) register loopback redirect URIs
# over plain http; every other client must use https. Any other scheme
# (``javascript:``, ``data:``, custom app schemes) is rejected.
_LOOPBACK_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})


def is_valid_redirect_uri(uri: str) -> bool:
    """Return whether *uri* is acceptable as a registered redirect URI."""
    if not uri or any(c.isspace() for c in uri):
        return False
    parsed = urlparse.urlparse(uri)
    # Userinfo (``https://trusted@evil/``) makes the host hard to read on
    # the consent page, and no real client needs it.
    if parsed.fragment or '@' in parsed.netloc:
        return False
    try:
        parsed.port  # noqa: B018 -- raises ValueError for a bad port
    except ValueError:
        return False
    if parsed.scheme == 'https' and parsed.netloc:
        return True
    if parsed.scheme == 'http':
        return (parsed.hostname or '') in _LOOPBACK_HOSTS
    return False


def display_host(uri: str) -> str:
    """Return the host (and a non-default port) that *uri* redirects to."""
    parsed = urlparse.urlsplit(uri)
    host = parsed.hostname or ''
    default = {'http': 80, 'https': 443}.get(parsed.scheme)
    if parsed.port and parsed.port != default:
        return f'{host}:{parsed.port}'
    return host


async def register_client(
    db: graph.Graph,
    *,
    redirect_uris: list[str],
    client_name: str | None,
    grant_types: list[str],
    response_types: list[str],
    token_endpoint_auth_method: str,
    scope: str | None,
) -> models.OAuthClient:
    """Persist a new public OAuth client and return it."""
    client = models.OAuthClient(
        client_id=f'mcp_{nanoid.generate()}',
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=grant_types,
        response_types=response_types,
        token_endpoint_auth_method=token_endpoint_auth_method,
        scope=scope,
    )
    await db.create(client)
    LOGGER.info(
        'Registered OAuth client %s (%s)',
        client.client_id,
        client_name or '-',
    )
    return client


async def get_client(
    db: graph.Graph, client_id: str
) -> models.OAuthClient | None:
    """Look up a registered OAuth client by ``client_id``."""
    results = await db.match(models.OAuthClient, {'client_id': client_id})
    return results[0] if results else None
