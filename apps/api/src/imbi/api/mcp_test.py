"""One-shot connection testing for :class:`~imbi.common.models.MCPServer`.

The admin UI needs to verify that a configured MCP server is reachable,
authenticates correctly, and lists its tools. This module opens a single
streamable-HTTP MCP session, measures round-trip latency, and discovers
the server's tools, then tears the session down.

It deliberately mirrors the connect/auth logic in
``imbi.assistant.external_mcp`` (which maintains long-lived connections for
the running assistant) rather than importing it: the assistant is a
separate service and is not a dependency of the API.
"""

import asyncio
import collections.abc
import contextlib
import dataclasses
import logging
import time
import typing

import httpx
import mcp
from mcp.client import streamable_http
from mcp.shared._httpx_utils import create_mcp_http_client

from imbi.common import models
from imbi.common.auth.encryption import decrypt_config_value

LOGGER = logging.getLogger(__name__)

# A successful connection slower than this is reported as ``degraded``
# rather than ``healthy``.
DEGRADED_LATENCY_MS = 1000

_OAUTH_EXPIRY_BUFFER = 60.0

_OAUTH_TOKEN_TIMEOUT = 10.0

Status = typing.Literal['healthy', 'degraded', 'unreachable']


@dataclasses.dataclass(slots=True)
class ConnectionTestResult:
    """Outcome of a single MCP server connection test."""

    ok: bool
    status: Status
    latency_ms: int
    tools: list[str]
    error: str | None = None


class OAuthClientCredentialsAuth(httpx.Auth):
    """httpx Auth that fetches an OAuth client-credentials token.

    Unlike the assistant's long-lived variant, this is used for a single
    test and does not need refresh-ahead caching.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None = None,
        *,
        verify_ssl: bool = True,
        timeout_s: float = _OAUTH_TOKEN_TIMEOUT,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._verify_ssl = verify_ssl
        self._timeout_s = timeout_s

    async def _fetch_token(self) -> str:
        data: dict[str, str] = {
            'grant_type': 'client_credentials',
            'client_id': self._client_id,
            'client_secret': self._client_secret,
        }
        if self._scope:
            data['scope'] = self._scope
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_s),
            verify=self._verify_ssl,
        ) as client:
            response = await client.post(self._token_url, data=data)
            response.raise_for_status()
            return str(response.json()['access_token'])

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> collections.abc.AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._fetch_token()
        request.headers['Authorization'] = f'Bearer {token}'
        yield request


def _build_auth(
    server: models.MCPServer,
) -> tuple[dict[str, str] | None, httpx.Auth | None]:
    """Resolve request headers and httpx auth, decrypting any secrets.

    Returns:
        Tuple of (static headers or None, httpx.Auth or None).

    Raises:
        ValueError: If the server's auth configuration is incomplete.

    """
    if server.auth_type == 'static':
        value = decrypt_config_value(server.static_value_encrypted)
        if server.static_header and value is not None:
            return {server.static_header: value}, None
        raise ValueError('Static auth is missing a header or value')
    if server.auth_type == 'oauth_client_credentials':
        secret = decrypt_config_value(server.oauth_client_secret_encrypted)
        if server.oauth_token_url and server.oauth_client_id and secret:
            return None, OAuthClientCredentialsAuth(
                token_url=str(server.oauth_token_url),
                client_id=server.oauth_client_id,
                client_secret=secret,
                scope=server.oauth_scope,
                verify_ssl=server.verify_ssl,
                timeout_s=float(server.timeout),
            )
        raise ValueError('OAuth auth is missing configuration')
    return None, None


async def test_connection(server: models.MCPServer) -> ConnectionTestResult:
    """Open a streamable-HTTP session, list tools, and time the round trip.

    Never raises: a connection or auth failure is returned as an
    ``unreachable`` result with the error message.

    Parameters:
        server: The MCP server to test. Secrets are read from the
            ``*_encrypted`` fields and decrypted at connect time.

    Returns:
        The test outcome, including discovered tool names and latency.

    """
    timeout_s = float(server.timeout)
    started = time.monotonic()
    try:
        headers, http_auth = _build_auth(server)
        if server.verify_ssl:
            http_client = create_mcp_http_client(
                headers, httpx.Timeout(timeout_s), http_auth
            )
        else:
            http_client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(timeout_s),
                auth=http_auth,
                follow_redirects=True,
                verify=False,  # noqa: S501 - opt-in for in-cluster endpoints
            )
        async with contextlib.AsyncExitStack() as stack:
            streams = await stack.enter_async_context(
                streamable_http.streamable_http_client(
                    str(server.url), http_client=http_client
                )
            )
            session = await stack.enter_async_context(
                mcp.ClientSession(streams[0], streams[1])
            )
            await asyncio.wait_for(session.initialize(), timeout=timeout_s)
            result = await asyncio.wait_for(
                session.list_tools(), timeout=timeout_s
            )
            tools = [tool.name for tool in result.tools]
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        latency_ms = int((time.monotonic() - started) * 1000)
        return ConnectionTestResult(
            ok=False,
            status='unreachable',
            latency_ms=latency_ms,
            tools=[],
            error=f'Timed out after {server.timeout}s',
        )
    except Exception as err:  # noqa: BLE001 - any failure is a failed test
        latency_ms = int((time.monotonic() - started) * 1000)
        LOGGER.info('MCP connection test for %r failed: %s', server.slug, err)
        return ConnectionTestResult(
            ok=False,
            status='unreachable',
            latency_ms=latency_ms,
            tools=[],
            error=str(err) or err.__class__.__name__,
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    status: Status = (
        'degraded' if latency_ms >= DEGRADED_LATENCY_MS else 'healthy'
    )
    return ConnectionTestResult(
        ok=True,
        status=status,
        latency_ms=latency_ms,
        tools=tools,
        error=None,
    )


__all__ = ['ConnectionTestResult', 'test_connection']
