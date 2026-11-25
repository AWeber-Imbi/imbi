"""The catalog of tools that an agent can use.

The catalog is the list of Imbi tools: the tools that imbi-mcp and
imbi-assistant make from the OpenAPI document of this API. This module
makes them in the same way, in this process, so the names are the
same. The MCP servers in Admin > Assistant are for the assistant only.
An agent gets other MCP servers from the plugins of its marketplaces.

When the tools cannot be made, the catalog has an :data:`ErrorCode` in
``error`` and no tools. The error text goes only to the log, never to
the response or to the cache. The catalog is kept in Valkey for
:data:`CACHE_TTL_SECONDS`.

A tool key is ``imbi.<tool name>``. An agent stores its tool
configuration by this key.

The catalog also lists the opt-in Claude Code built-in tools in
``builtin_tools``, as ``builtin.<tool name>``. They are off for each
agent until its tool map has the key. They do not come from the
OpenAPI document, so a catalog error does not change them.
"""

import asyncio
import collections.abc
import datetime
import logging
import typing

import fastapi
import fastmcp
import httpx
import pydantic
from mcp import types as mcp_types
from valkey import asyncio as valkey

from imbi.common import mcp as common_mcp
from imbi.common import models

LOGGER = logging.getLogger(__name__)

#: Change the version suffix when the catalog shape changes, so that
#: entries in the old shape are not read.
CACHE_KEY = 'imbi:agents:tool-catalog:v2'
CACHE_TTL_SECONDS = 300

#: The read-only Imbi routes whose tools every agent has, as
#: ``"METHOD /template"`` without the API prefix (the form of
#: :mod:`imbi.api.auth.agent_api_routes`). A tool name holds the API
#: prefix, so :func:`index` finds the names when the app starts.
DEFAULT_ROUTES: frozenset[str] = frozenset(
    {
        # Projects and search
        'GET /organizations/{org_slug}/projects/',
        'GET /organizations/{org_slug}/projects/{project_id}',
        'GET /organizations/{org_slug}/projects/{project_id}/relationships',
        'GET /organizations/{org_slug}/projects/{project_id}/events/',
        'GET /organizations/{org_slug}/search',
        # Documents
        'GET /organizations/{org_slug}/documents/',
        'GET /organizations/{org_slug}/documents/{document_id}',
        'GET /organizations/{org_slug}/documents/{document_id}/versions',
        'GET /organizations/{org_slug}/documents/{document_id}/versions/'
        '{version}',
        'GET /organizations/{org_slug}/projects/{project_id}/documents/',
        'GET /organizations/{org_slug}/projects/{project_id}/documents/'
        '{document_id}',
        # Tickets
        'GET /organizations/{org_slug}/tickets/',
        'GET /organizations/{org_slug}/tickets/counts',
        'GET /organizations/{org_slug}/tickets/labels',
        'GET /organizations/{org_slug}/tickets/{short_id}',
        'GET /organizations/{org_slug}/tickets/{short_id}/events',
        'GET /organizations/{org_slug}/tickets/{short_id}/projects',
        'GET /organizations/{org_slug}/tickets/{short_id}/relations',
        # Operations log, pull requests, and drift
        'GET /organizations/{org_slug}/projects/{project_id}/operations-log/',
        'GET /organizations/{org_slug}/pull-requests/',
        'GET /organizations/{org_slug}/pull-requests/activity',
        'GET /organizations/{org_slug}/projects/{project_id}/pull-requests/',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'release-drift',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'recent-commits',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'refs/{ref:path}/commits',
        # Environments
        'GET /organizations/{org_slug}/environments/',
        'GET /organizations/{org_slug}/environments/{slug}',
        'GET /organizations/{org_slug}/environments/{slug}/edges/{rel_type}',
        # Releases
        'GET /organizations/{org_slug}/projects/{project_id}/releases/',
        'GET /organizations/{org_slug}/projects/{project_id}/releases/current',
        'GET /organizations/{org_slug}/projects/{project_id}/releases/'
        '{release_id}',
        'GET /organizations/{org_slug}/projects/{project_id}/releases/'
        '{release_id}/dependencies',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'release-history',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'releases/{tag}/blockers',
        # Deployments
        'GET /organizations/{org_slug}/projects/{project_id}/releases/'
        '{release_id}/environments',
        'GET /organizations/{org_slug}/projects/{project_id}/releases/'
        '{release_id}/environments/{env_slug}',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'environments/{env_slug}/deployments/{deployment_id}',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'runs/{run_id}',
        'GET /organizations/{org_slug}/projects/{project_id}/deployments/'
        'sync-status',
        'GET /organizations/{org_slug}/pull-requests/pending-deploy',
        # Components
        'GET /organizations/{org_slug}/components/',
        'GET /organizations/{org_slug}/components/{component_id}/usage',
        'GET /organizations/{org_slug}/component-releases/'
        '{component_release_id}/notes',
        'GET /organizations/{org_slug}/component-releases/'
        '{component_release_id}/advisories',
        'GET /cves/{cve_id}',
    }
)

#: The tool keys of :data:`DEFAULT_ROUTES`. :func:`index` sets them.
_default_tools: frozenset[str] = frozenset()


def index(app: fastapi.FastAPI) -> None:
    """Find the tool keys of :data:`DEFAULT_ROUTES`, after
    :func:`imbi.api.auth.agent_api.index` keeps the route keys.

    The name is the one that fastmcp gives
    (``OpenAPIProvider._generate_default_name``): the operation id up to
    the first ``__``, at most 56 characters. A FastAPI operation id has
    only the characters that its slug step keeps. A test checks the
    names against the catalog.
    """
    global _default_tools
    keys = app.state.agent_api_routes
    _default_tools = frozenset(
        f'imbi.{route.unique_id.split("__")[0][:56]}'
        for route in app.routes
        if isinstance(route, fastapi.routing.APIRoute)
        for method in route.methods
        if keys.get((route.endpoint, method)) in DEFAULT_ROUTES
    )


def default_tools() -> frozenset[str]:
    """The tool keys that every agent has."""
    return _default_tools


def with_default_tools(tools: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Return the tool map ``tools`` with the default tools added.

    An entry in ``tools`` wins over the default configuration.
    """
    return {**{key: {} for key in _default_tools}, **tools}


#: The maximum length of a tool description in the catalog.
DESCRIPTION_LENGTH = 300

Capability = typing.Literal['read', 'write', 'destructive', 'unknown']

#: Why the tools could not be listed. ``auth_failed`` is
#: an HTTP 401 or 403 response. ``unreachable`` is each other failure.
ErrorCode = typing.Literal['unreachable', 'timeout', 'auth_failed']


class AgentCatalogTool(pydantic.BaseModel):
    #: ``imbi.<tool name>`` or ``builtin.<tool name>``.
    key: str
    name: str
    description: str | None = None
    capability: Capability
    #: On for every agent (:data:`DEFAULT_ROUTES`).
    default: bool = False


#: The catalog entries of the opt-in built-in tools, by name.
BUILTIN_CATALOG = tuple(
    AgentCatalogTool(
        key=tool.key,
        name=tool.name,
        description=tool.description,
        capability=tool.capability,
    )
    for tool in sorted(
        models.OPT_IN_BUILTIN_TOOLS.values(), key=lambda t: t.name
    )
)


class AgentToolCatalog(pydantic.BaseModel):
    #: A kept copy in another form, for example the grouped form of an
    #: earlier release, does not validate, so it is listed again.
    model_config = pydantic.ConfigDict(extra='forbid')

    tools: list[AgentCatalogTool] = []
    #: The opt-in Claude Code built-in tools.
    builtin_tools: list[AgentCatalogTool] = pydantic.Field(
        default_factory=lambda: list(BUILTIN_CATALOG)
    )
    #: Set when the tools could not be listed.
    error: ErrorCode | None = None
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
    name: str,
    description: str | None,
    annotations: mcp_types.ToolAnnotations | None,
) -> AgentCatalogTool:
    return AgentCatalogTool(
        key=f'imbi.{name}',
        name=name,
        description=_summary(description),
        capability=capability(annotations),
        default=f'imbi.{name}' in _default_tools,
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
        mcp_component_fn=common_mcp.annotate,
    )


async def build_catalog(spec: dict[str, typing.Any]) -> AgentToolCatalog:
    """List the Imbi tools from the OpenAPI document now. Never raises."""
    catalog = AgentToolCatalog(
        generated_at=datetime.datetime.now(datetime.UTC)
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
        catalog.error = _error_code(err)
        return catalog
    catalog.tools = sorted(
        (_tool(t.name, t.description, t.annotations) for t in tools),
        key=lambda t: t.name,
    )
    return catalog


async def get_catalog(
    client: valkey.Valkey | None,
    spec: collections.abc.Callable[[], dict[str, typing.Any]],
    *,
    refresh: bool = False,
) -> AgentToolCatalog:
    """Return the catalog from Valkey, or list it and keep it there.

    ``refresh`` lists the catalog again and replaces the kept copy.
    Without Valkey, each call lists the catalog. A kept copy that does
    not validate, for example one from an earlier release, is listed
    again.
    """
    if client is not None and not refresh:
        try:
            cached = await client.get(CACHE_KEY)
        except Exception:  # noqa: BLE001
            LOGGER.debug('tool catalog cache read failed', exc_info=True)
            cached = None
        if cached is not None:
            try:
                # The built-in tools come from this release, not the
                # kept copy.
                return AgentToolCatalog.model_validate_json(cached).model_copy(
                    update={'builtin_tools': list(BUILTIN_CATALOG)}
                )
            except pydantic.ValidationError:
                LOGGER.debug('discarding malformed tool catalog cache entry')
    catalog = await build_catalog(spec())
    if client is not None:
        try:
            await client.set(
                CACHE_KEY, catalog.model_dump_json(), ex=CACHE_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001
            LOGGER.debug('tool catalog cache write failed', exc_info=True)
    return catalog
