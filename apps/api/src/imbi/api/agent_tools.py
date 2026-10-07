"""The catalog of tools that an agent can use.

The catalog has one group for each tool server:

* ``imbi``: the tools that imbi-mcp and imbi-assistant make from the
  OpenAPI document of this API. This module makes them in the same
  way, in this process, so the names are the same.
* One group for each enabled :class:`~imbi.common.models.MCPServer`.
  The tools are listed live, with the client code of the connection
  test. ``ignored_tools`` is applied.

A server that fails gives its group with an :data:`ErrorCode` in
``error`` and no tools. The other groups are not affected. The error
text can show internal hosts, URLs, or parts of credentials, so it
goes only to the log, never to the response or to the cache. The
catalog is kept in Valkey for :data:`CACHE_TTL_SECONDS`.

A tool key is ``<server slug>.<tool name>``. An agent stores its tool
configuration by this key.
"""

import asyncio
import collections.abc
import datetime
import logging
import typing

import fastmcp
import fastmcp.tools
import httpx
import pydantic
from mcp import types as mcp_types
from valkey import asyncio as valkey

from imbi.api import mcp_test
from imbi.common import graph, models
from imbi.common import mcp as common_mcp

if typing.TYPE_CHECKING:
    from fastmcp.utilities.components import FastMCPComponent
    from fastmcp.utilities.openapi import HTTPRoute

LOGGER = logging.getLogger(__name__)

CACHE_KEY = 'imbi:agents:tool-catalog'
CACHE_TTL_SECONDS = 300

#: The limit for one MCP server, in seconds. A server with a smaller
#: ``timeout`` uses its own value.
SERVER_TIMEOUT_SECONDS = 10.0

#: The server slug of the Imbi tools.
IMBI_SERVER_SLUG = 'imbi'

#: The maximum length of a tool description in the catalog.
DESCRIPTION_LENGTH = 300

Capability = typing.Literal['read', 'write', 'destructive', 'unknown']
Transport = typing.Literal['internal', 'mcp/http']

#: Why the tools of a server could not be listed. ``auth_failed`` is
#: an HTTP 401 or 403 response. ``unreachable`` is each other failure.
ErrorCode = typing.Literal['unreachable', 'timeout', 'auth_failed']


class AgentToolServer(pydantic.BaseModel):
    slug: str
    name: str
    transport: Transport


class AgentCatalogTool(pydantic.BaseModel):
    #: ``<server slug>.<tool name>``.
    key: str
    name: str
    description: str | None = None
    capability: Capability


class AgentToolGroup(pydantic.BaseModel):
    server: AgentToolServer
    tools: list[AgentCatalogTool] = []
    #: Set when the tools of this server could not be listed.
    error: ErrorCode | None = None


class AgentToolCatalog(pydantic.BaseModel):
    groups: list[AgentToolGroup]
    generated_at: datetime.datetime


def capability(annotations: mcp_types.ToolAnnotations | None) -> Capability:
    """Return the capability that the MCP tool annotations tell.

    ``readOnlyHint`` gives ``read`` and ``destructiveHint`` gives
    ``destructive``. A tool with one of the hints set to false gives
    ``write``. A tool without the two hints gives ``unknown``.
    """
    if annotations is None or (
        annotations.readOnlyHint is None
        and annotations.destructiveHint is None
    ):
        return 'unknown'
    if annotations.readOnlyHint:
        return 'read'
    if annotations.destructiveHint:
        return 'destructive'
    return 'write'


def _summary(description: str | None) -> str | None:
    """Return the first paragraph of a description, made short."""
    if not description:
        return None
    first = description.strip().split('\n\n', 1)[0]
    text = ' '.join(first.split())
    if len(text) > DESCRIPTION_LENGTH:
        text = text[: DESCRIPTION_LENGTH - 1].rstrip() + '…'
    return text or None


def _tool(
    server_slug: str,
    name: str,
    description: str | None,
    annotations: mcp_types.ToolAnnotations | None,
) -> AgentCatalogTool:
    return AgentCatalogTool(
        key=f'{server_slug}.{name}',
        name=name,
        description=_summary(description),
        capability=capability(annotations),
    )


def _error_code(err: BaseException) -> ErrorCode:
    """Return the error code of ``err``.

    The errors in a group and the ``__cause__`` of each error are
    examined too.
    """
    pending: list[BaseException] = [err]
    while pending:
        item = pending.pop()
        if isinstance(item, httpx.HTTPStatusError) and (
            item.response.status_code in {401, 403}
        ):
            return 'auth_failed'
        if isinstance(item, TimeoutError | httpx.TimeoutException):
            return 'timeout'
        if isinstance(item, BaseExceptionGroup):
            group = typing.cast('BaseExceptionGroup[BaseException]', item)
            pending.extend(group.exceptions)
        if item.__cause__ is not None:
            pending.append(item.__cause__)
    return 'unreachable'


async def _mcp_group(server: models.MCPServer) -> AgentToolGroup:
    """List the tools of one MCP server. Never raises."""
    group = AgentToolGroup(
        server=AgentToolServer(
            slug=server.slug, name=server.name, transport='mcp/http'
        )
    )
    timeout_s = min(float(server.timeout), SERVER_TIMEOUT_SECONDS)
    try:
        async with asyncio.timeout(timeout_s):
            tools = await mcp_test.list_tools(server, timeout_s)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        LOGGER.warning(
            'Cannot list the tools of %r: timed out after %gs',
            server.slug,
            timeout_s,
        )
        group.error = 'timeout'
        return group
    except Exception as err:  # noqa: BLE001 - one server must not fail all
        LOGGER.warning(
            'Cannot list the tools of %r: %s', server.slug, err, exc_info=err
        )
        group.error = _error_code(err)
        return group
    ignored = set(server.ignored_tools)
    group.tools = sorted(
        (
            _tool(server.slug, t.name, t.description, t.annotations)
            for t in tools
            if t.name not in ignored
        ),
        key=lambda t: t.name,
    )
    return group


def _annotate(route: HTTPRoute, component: FastMCPComponent) -> None:
    """Set the tool annotations from the HTTP method of the operation."""
    if isinstance(component, fastmcp.tools.Tool):
        method = route.method.upper()
        component.annotations = mcp_types.ToolAnnotations(
            readOnlyHint=method in {'GET', 'HEAD'},
            destructiveHint=method == 'DELETE',
        )


def _imbi_server(
    spec: dict[str, typing.Any], client: httpx.AsyncClient
) -> fastmcp.FastMCP[typing.Any]:
    """Make the Imbi tools as imbi-mcp and imbi-assistant do."""
    return fastmcp.FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name='Imbi',
        route_maps=common_mcp.excluded_route_maps(spec),
        route_map_fn=common_mcp.exclude_non_ai_tools,
        mcp_component_fn=_annotate,
    )


async def _imbi_group(spec: dict[str, typing.Any]) -> AgentToolGroup:
    """List the Imbi tools from the OpenAPI document. Never raises."""
    group = AgentToolGroup(
        server=AgentToolServer(
            slug=IMBI_SERVER_SLUG, name='Imbi', transport='internal'
        )
    )
    try:
        # The client is not used: no tool is called.
        async with httpx.AsyncClient() as client:
            # The parse of a large document blocks, so do it in a
            # thread.
            server = await asyncio.to_thread(_imbi_server, spec, client)
            tools = await server.list_tools(run_middleware=False)
    except asyncio.CancelledError:
        raise
    except Exception as err:
        LOGGER.exception('Cannot make the Imbi tools')
        group.error = _error_code(err)
        return group
    group.tools = sorted(
        (
            _tool(IMBI_SERVER_SLUG, t.name, t.description, t.annotations)
            for t in tools
        ),
        key=lambda t: t.name,
    )
    return group


async def build_catalog(
    db: graph.Pool, spec: dict[str, typing.Any]
) -> AgentToolCatalog:
    """List every group now, at the same time."""
    servers = await db.match(
        models.MCPServer, {'enabled': True}, order_by='name'
    )
    groups = await asyncio.gather(
        _imbi_group(spec), *(_mcp_group(server) for server in servers)
    )
    return AgentToolCatalog(
        groups=list(groups),
        generated_at=datetime.datetime.now(datetime.UTC),
    )


async def get_catalog(
    db: graph.Pool,
    client: valkey.Valkey | None,
    spec: collections.abc.Callable[[], dict[str, typing.Any]],
    *,
    refresh: bool = False,
) -> AgentToolCatalog:
    """Return the catalog from Valkey, or list it and keep it there.

    ``refresh`` lists the catalog again and replaces the kept copy.
    Without Valkey, each call lists the catalog. A kept copy that does
    not validate, for example one with error text from an earlier
    release, is listed again.
    """
    if client is not None and not refresh:
        try:
            cached = await client.get(CACHE_KEY)
        except Exception:  # noqa: BLE001
            LOGGER.debug('tool catalog cache read failed', exc_info=True)
            cached = None
        if cached is not None:
            try:
                return AgentToolCatalog.model_validate_json(cached)
            except pydantic.ValidationError:
                LOGGER.debug('discarding malformed tool catalog cache entry')
    catalog = await build_catalog(db, spec())
    if client is not None:
        try:
            await client.set(
                CACHE_KEY, catalog.model_dump_json(), ex=CACHE_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001
            LOGGER.debug('tool catalog cache write failed', exc_info=True)
    return catalog
