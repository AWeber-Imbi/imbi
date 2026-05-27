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
import psycopg.errors
import pydantic
from imbi_common import graph, models
from imbi_common.auth.encryption import encrypt_config_value

from imbi_api.auth import permissions
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
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


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
    try:
        records = await db.execute(query, props, ['n'])
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'MCP server with slug {node.slug!r} already exists',
        ) from e
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
    try:
        records = await db.execute(query, {**props, 'id': id}, ['n'])
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'MCP server with slug {node.slug!r} already exists',
        ) from e
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
