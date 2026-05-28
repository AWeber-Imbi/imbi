"""Admin CRUD endpoints for MCPServer global configuration.

``MCPServer`` is global config — it has no organization edge. Secrets
(``static_value`` and ``oauth_client_secret``) are accepted as plaintext
request fields, encrypted via :mod:`imbi_common.auth.encryption`, and
persisted only as ciphertext in the ``*_encrypted`` model fields.
Responses never expose plaintext or ciphertext secrets; instead they
surface ``has_static_value`` / ``has_oauth_client_secret`` booleans.
"""

import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph, models
from imbi_common.auth.encryption import encrypt_config_value

from imbi_api import mcp_test
from imbi_api.auth import permissions
from imbi_api.endpoints._helpers import conflict_on_unique_violation
from imbi_api.graph_sql import props_template, set_clause

LOGGER = logging.getLogger(__name__)

mcp_servers_router = fastapi.APIRouter(
    prefix='/mcp-servers',
    tags=['MCP Servers'],
)

AuthType = typing.Literal['none', 'static', 'oauth_client_credentials']


class MCPServerCreate(pydantic.BaseModel):
    """Request model for creating an MCP server.

    Secrets (``static_value`` and ``oauth_client_secret``) are plaintext
    here and are encrypted before persistence.
    """

    name: str
    slug: str
    url: pydantic.HttpUrl
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    enabled: bool = True
    tool_prefix: str | None = None
    timeout: int = 30
    verify_ssl: bool = True
    ignored_tools: list[str] = pydantic.Field(default_factory=list)
    auth_type: AuthType = 'none'
    static_header: str | None = None
    static_value: str | None = None
    oauth_token_url: pydantic.HttpUrl | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_scope: str | None = None


class MCPServerUpdate(pydantic.BaseModel):
    """Request model for partially updating an MCP server.

    Every field is optional. An omitted secret field leaves the stored
    ciphertext unchanged; an explicit ``null``/empty value clears it; a
    new value re-encrypts it. ``exclude_unset`` on the parsed model is
    used to distinguish "omitted" from "explicitly null".
    """

    name: str | None = None
    slug: str | None = None
    url: pydantic.HttpUrl | None = None
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    enabled: bool | None = None
    tool_prefix: str | None = None
    timeout: int | None = None
    verify_ssl: bool | None = None
    ignored_tools: list[str] | None = None
    auth_type: AuthType | None = None
    static_header: str | None = None
    static_value: str | None = None
    oauth_token_url: pydantic.HttpUrl | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_scope: str | None = None


class MCPServerResponse(pydantic.BaseModel):
    """Response model for an MCP server.

    Secrets are never returned; their presence is surfaced via the
    ``has_static_value`` and ``has_oauth_client_secret`` booleans.
    """

    id: str
    name: str
    slug: str
    url: pydantic.HttpUrl
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    enabled: bool = True
    tool_prefix: str | None = None
    timeout: int = 30
    verify_ssl: bool = True
    ignored_tools: list[str] = pydantic.Field(default_factory=list)
    auth_type: AuthType = 'none'
    static_header: str | None = None
    has_static_value: bool = False
    oauth_token_url: pydantic.HttpUrl | None = None
    oauth_client_id: str | None = None
    has_oauth_client_secret: bool = False
    oauth_scope: str | None = None
    status: typing.Literal['unknown', 'healthy', 'degraded', 'unreachable'] = (
        'unknown'
    )
    last_tested_at: datetime.datetime | None = None
    last_tested_latency_ms: int | None = None
    tools_discovered: int | None = None
    last_error: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class MCPServerTestConfig(MCPServerCreate):
    """Request body for testing an unsaved configuration.

    Same shape as :class:`MCPServerCreate`, but ``name`` and ``slug`` are
    optional because the connection test only needs the URL and auth.
    """

    name: str = '__connection_test__'
    slug: str = '__connection_test__'


class MCPServerTestResult(pydantic.BaseModel):
    """Outcome of an MCP server connection test."""

    ok: bool
    status: typing.Literal['healthy', 'degraded', 'unreachable']
    latency_ms: int
    tools: list[str]
    tools_discovered: int
    error: str | None = None
    tested_at: datetime.datetime


class MCPServerStatusReport(pydantic.BaseModel):
    """Runtime status report, posted by the assistant on tool failure."""

    status: typing.Literal['healthy', 'degraded', 'unreachable']
    error: str | None = None


def _to_response(node: models.MCPServer) -> MCPServerResponse:
    """Build a secret-free response from a persisted MCPServer node."""
    return MCPServerResponse(
        id=node.id,
        name=node.name,
        slug=node.slug,
        url=node.url,
        description=node.description,
        icon=node.icon,
        enabled=node.enabled,
        tool_prefix=node.tool_prefix,
        timeout=node.timeout,
        verify_ssl=node.verify_ssl,
        ignored_tools=node.ignored_tools,
        auth_type=node.auth_type,
        static_header=node.static_header,
        has_static_value=node.static_value_encrypted is not None,
        oauth_token_url=node.oauth_token_url,
        oauth_client_id=node.oauth_client_id,
        has_oauth_client_secret=(
            node.oauth_client_secret_encrypted is not None
        ),
        oauth_scope=node.oauth_scope,
        status=node.status,
        last_tested_at=node.last_tested_at,
        last_tested_latency_ms=node.last_tested_latency_ms,
        tools_discovered=node.tools_discovered,
        last_error=node.last_error,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


@mcp_servers_router.post(
    '/', response_model=MCPServerResponse, status_code=201
)
async def create_mcp_server(
    data: MCPServerCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:create')),
    ],
) -> MCPServerResponse:
    """Create a new MCP server.

    Parameters:
        data: MCP server data; ``slug`` must be unique. ``static_value``
            and ``oauth_client_secret`` are plaintext and are encrypted
            before persistence.

    Returns:
        The created MCP server, without any secret values.

    Raises:
        409: If an MCP server with the same slug already exists.

    """
    _ = auth
    try:
        node = models.MCPServer(
            name=data.name,
            slug=data.slug,
            url=data.url,
            description=data.description,
            icon=data.icon,
            enabled=data.enabled,
            tool_prefix=data.tool_prefix,
            timeout=data.timeout,
            verify_ssl=data.verify_ssl,
            ignored_tools=data.ignored_tools,
            auth_type=data.auth_type,
            static_header=data.static_header,
            static_value_encrypted=encrypt_config_value(data.static_value),
            oauth_token_url=data.oauth_token_url,
            oauth_client_id=data.oauth_client_id,
            oauth_client_secret_encrypted=encrypt_config_value(
                data.oauth_client_secret
            ),
            oauth_scope=data.oauth_scope,
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    node.created_at = now
    node.updated_at = now
    props = node.model_dump(mode='json')
    query = f'CREATE (n:MCPServer {props_template(props)}) RETURN n'
    with conflict_on_unique_violation(
        f'MCP server with slug {node.slug!r} already exists',
    ):
        records = await db.execute(query, props, ['n'])
    if not records:
        raise fastapi.HTTPException(
            status_code=500,
            detail='MCP server create returned no rows',
        )
    return _to_response(_parse_node(records[0]['n']))


@mcp_servers_router.get('/', response_model=list[MCPServerResponse])
async def list_mcp_servers(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:read')),
    ],
) -> list[MCPServerResponse]:
    """List all MCP servers ordered by name.

    Returns:
        Every MCP server, without any secret values.

    """
    _ = auth
    nodes = await db.match(models.MCPServer, order_by='name')
    return [_to_response(node) for node in nodes]


@mcp_servers_router.get('/{id}', response_model=MCPServerResponse)
async def get_mcp_server(
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:read')),
    ],
) -> MCPServerResponse:
    """Get an MCP server by id.

    Parameters:
        id: The MCP server id.

    Returns:
        The MCP server, without any secret values.

    Raises:
        404: If no MCP server with the given id exists.

    """
    _ = auth
    node = await _fetch(db, id)
    return _to_response(node)


@mcp_servers_router.patch('/{id}', response_model=MCPServerResponse)
async def update_mcp_server(
    id: str,
    data: MCPServerUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:update')),
    ],
) -> MCPServerResponse:
    """Partially update an MCP server.

    Omitted fields are left unchanged. For the secret fields
    (``static_value``/``oauth_client_secret``): an omitted field leaves
    the stored ciphertext unchanged; an explicit ``null``/empty value
    clears it; a new value re-encrypts it.

    Parameters:
        id: The MCP server id.
        data: Fields to update.

    Returns:
        The updated MCP server, without any secret values.

    Raises:
        404: If no MCP server with the given id exists.
        409: If the new slug collides with another MCP server.

    """
    _ = auth
    existing = await _fetch(db, id)
    set_fields = data.model_dump(exclude_unset=True)

    updates: dict[str, typing.Any] = {}
    for field in (
        'name',
        'slug',
        'url',
        'description',
        'icon',
        'enabled',
        'tool_prefix',
        'timeout',
        'verify_ssl',
        'ignored_tools',
        'auth_type',
        'static_header',
        'oauth_token_url',
        'oauth_client_id',
        'oauth_scope',
    ):
        if field in set_fields:
            updates[field] = set_fields[field]

    if 'static_value' in set_fields:
        updates['static_value_encrypted'] = encrypt_config_value(
            set_fields['static_value']
        )
    if 'oauth_client_secret' in set_fields:
        updates['oauth_client_secret_encrypted'] = encrypt_config_value(
            set_fields['oauth_client_secret']
        )

    if not updates:
        return _to_response(existing)

    merged = existing.model_dump()
    merged.update(updates)
    try:
        node = models.MCPServer.model_validate(merged)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e
    node.updated_at = datetime.datetime.now(datetime.UTC)

    props = node.model_dump(mode='json', exclude={'id', 'created_at'})
    set_stmt = set_clause('n', props)
    query = f'MATCH (n:MCPServer {{{{id: {{id}}}}}}) {set_stmt} RETURN n'
    with conflict_on_unique_violation(
        f'MCP server with slug {node.slug!r} already exists',
    ):
        records = await db.execute(query, {**props, 'id': id}, ['n'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'MCP server with id {id!r} not found',
        )
    return _to_response(_parse_node(records[0]['n']))


@mcp_servers_router.delete('/{id}', status_code=204)
async def delete_mcp_server(
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:delete')),
    ],
) -> None:
    """Delete an MCP server by id.

    Parameters:
        id: The id of the MCP server to delete.

    Raises:
        404: If no MCP server with the given id exists.

    """
    _ = auth
    query: typing.LiteralString = (
        'MATCH (n:MCPServer {{id: {id}}}) DETACH DELETE n RETURN n'
    )
    records = await db.execute(query, {'id': id})
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'MCP server with id {id!r} not found',
        )


@mcp_servers_router.post('/{id}/test', response_model=MCPServerTestResult)
async def test_mcp_server(
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:update')),
    ],
) -> MCPServerTestResult:
    """Test connectivity to a saved MCP server and persist the result.

    Opens a streamable-HTTP session using the server's stored
    configuration and secrets, lists its tools, and records the outcome
    (``status``, ``last_tested_at``, latency, tool count, and any error)
    on the node.

    Parameters:
        id: The MCP server id.

    Returns:
        The test result, including discovered tool names.

    Raises:
        404: If no MCP server with the given id exists.

    """
    _ = auth
    node = await _fetch(db, id)
    result = await mcp_test.test_connection(node)
    now = datetime.datetime.now(datetime.UTC)
    node.status = result.status
    node.last_tested_at = now
    node.last_tested_latency_ms = result.latency_ms
    node.tools_discovered = len(result.tools)
    node.last_error = result.error
    await _persist(db, node)
    return MCPServerTestResult(
        ok=result.ok,
        status=result.status,
        latency_ms=result.latency_ms,
        tools=result.tools,
        tools_discovered=len(result.tools),
        error=result.error,
        tested_at=now,
    )


@mcp_servers_router.post('/test', response_model=MCPServerTestResult)
async def test_mcp_server_config(
    data: MCPServerTestConfig,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:create')),
    ],
) -> MCPServerTestResult:
    """Test an unsaved MCP server configuration without persisting it.

    Used by the create form's "Test connection" action, where secrets are
    supplied as plaintext in the request and no record exists yet.

    Parameters:
        data: The candidate configuration; secrets are plaintext.

    Returns:
        The test result, including discovered tool names.

    Raises:
        400: If the configuration is invalid for its ``auth_type``.

    """
    _ = auth
    try:
        node = models.MCPServer(
            name=data.name,
            slug=data.slug,
            url=data.url,
            enabled=data.enabled,
            tool_prefix=data.tool_prefix,
            timeout=data.timeout,
            verify_ssl=data.verify_ssl,
            ignored_tools=data.ignored_tools,
            auth_type=data.auth_type,
            static_header=data.static_header,
            static_value_encrypted=encrypt_config_value(data.static_value),
            oauth_token_url=data.oauth_token_url,
            oauth_client_id=data.oauth_client_id,
            oauth_client_secret_encrypted=encrypt_config_value(
                data.oauth_client_secret
            ),
            oauth_scope=data.oauth_scope,
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e
    result = await mcp_test.test_connection(node)
    return MCPServerTestResult(
        ok=result.ok,
        status=result.status,
        latency_ms=result.latency_ms,
        tools=result.tools,
        tools_discovered=len(result.tools),
        error=result.error,
        tested_at=datetime.datetime.now(datetime.UTC),
    )


@mcp_servers_router.post('/{id}/status', response_model=MCPServerResponse)
async def report_mcp_server_status(
    id: str,
    data: MCPServerStatusReport,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('mcp_server:update')),
    ],
) -> MCPServerResponse:
    """Record a runtime health observation for an MCP server.

    Posted by the assistant when a live tool call against this server
    succeeds or fails, so the admin list reflects real usage health
    without a manual test. Updates ``status``, ``last_error``, and
    ``last_tested_at``; leaves configuration untouched.

    Parameters:
        id: The MCP server id.
        data: The observed status and optional error message.

    Returns:
        The updated MCP server, without any secret values.

    Raises:
        404: If no MCP server with the given id exists.

    """
    _ = auth
    node = await _fetch(db, id)
    node.status = data.status
    node.last_error = data.error
    node.last_tested_at = datetime.datetime.now(datetime.UTC)
    return _to_response(await _persist(db, node))


async def _persist(db: graph.Pool, node: models.MCPServer) -> models.MCPServer:
    """Write a mutated node back to the graph and return the result.

    ``id`` and ``created_at`` are preserved; every other property is
    overwritten from ``node``. ``updated_at`` is refreshed to the current
    UTC time so callers always observe fresh metadata.
    """
    node.updated_at = datetime.datetime.now(datetime.UTC)
    props = node.model_dump(mode='json', exclude={'id', 'created_at'})
    set_stmt = set_clause('n', props)
    query = f'MATCH (n:MCPServer {{{{id: {{id}}}}}}) {set_stmt} RETURN n'
    records = await db.execute(query, {**props, 'id': node.id}, ['n'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'MCP server with id {node.id!r} not found',
        )
    return _parse_node(records[0]['n'])


def _parse_node(raw: typing.Any) -> models.MCPServer:
    """Parse a graph agtype vertex into an MCPServer model."""
    props: typing.Any = graph.parse_agtype(raw)
    return models.MCPServer.model_validate(props)


async def _fetch(db: graph.Graph, id: str) -> models.MCPServer:
    """Fetch a single MCP server by id or raise 404."""
    results = await db.match(models.MCPServer, {'id': id})
    if not results:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'MCP server with id {id!r} not found',
        )
    return results[0]


__all__ = ['mcp_servers_router']
