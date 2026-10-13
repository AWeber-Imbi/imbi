"""Agent platform configuration and plugin marketplace routes (ADR 0022).

- ``/agent-platform-config``: the base Agent SDK configuration of the
  organization. Each change writes a new version. Agents can only
  narrow it (see :mod:`imbi.api.harness.platform`).
- ``/agent-marketplaces``: Claude Code plugin marketplaces, registered
  by git URL, and their synced plugin catalogs.

Members with ``agent:read`` read both, so the agent editor can list
plugins. ``agent_platform_config:write`` changes both.
"""

import datetime
import typing
import uuid

import fastapi
import psycopg.errors
import pydantic

from imbi.api import harness
from imbi.api.auth import organizations, permissions
from imbi.api.harness import marketplaces, platform
from imbi.common import graph

OrgId = organizations.MemberOrgId
Read = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('agent:read')),
]
Write = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(
        permissions.require_permission('agent_platform_config:write')
    ),
]


class PlatformConfigResponse(pydantic.BaseModel):
    #: ``None`` when the organization has no configuration yet: the
    #: defaults apply.
    version: int | None = None
    config: platform.AgentPlatformConfig
    created_by: str | None = None
    created_at: datetime.datetime | None = None


class MarketplaceCreate(pydantic.BaseModel):
    slug: str = pydantic.Field(
        min_length=1, max_length=63, pattern=r'^[a-z0-9][a-z0-9-]*$'
    )
    url: pydantic.HttpUrl = pydantic.Field(
        description='The git URL of the repository, for example '
        'https://github.com/anthropics/claude-code.'
    )


class MarketplaceResponse(pydantic.BaseModel):
    id: uuid.UUID
    slug: str
    url: str
    #: The name in marketplace.json.
    name: str | None = None
    description: str | None = None
    default_branch: str | None = None
    head_sha: str | None = None
    plugins: list[marketplaces.CatalogPlugin] = []
    synced_at: datetime.datetime | None = None
    sync_error: str | None = None
    created_by: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


# --- Configuration -----------------------------------------------------

agent_platform_config_router = fastapi.APIRouter(
    tags=['Agent Platform'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


def _config_response(
    version: int | None,
    config: platform.AgentPlatformConfig,
    row: dict[str, typing.Any] | None,
) -> PlatformConfigResponse:
    return PlatformConfigResponse(
        version=version,
        config=config,
        created_by=row['created_by'] if row else None,
        created_at=row['created_at'] if row else None,
    )


@agent_platform_config_router.get('/', response_model=PlatformConfigResponse)
async def get_agent_platform_config(
    org_id: OrgId, store: harness.Store, _: Read
) -> PlatformConfigResponse:
    """Return the newest configuration version of the organization."""
    row = await store.platform_config(org_id)
    version, config = await platform.load(store, org_id)
    return _config_response(version, config, row)


@agent_platform_config_router.put('/', response_model=PlatformConfigResponse)
async def put_agent_platform_config(
    org_id: OrgId,
    data: platform.AgentPlatformConfig,
    store: harness.Store,
    auth: Write,
) -> PlatformConfigResponse:
    """Write a new configuration version when the configuration changes.

    Default plugins are pinned like agent plugins: a plugin that keeps
    its ``sha`` keeps its pin, any other is pinned to the synced
    catalog.

    Raises:
        409: A concurrent write took the version.
        422: An allowed marketplace is not registered, or a default
            plugin is not in an allowed marketplace's catalog.

    """
    found = {row['slug']: row for row in await store.marketplaces(org_id)}
    missing = sorted(set(data.allowed_marketplaces) - set(found))
    if missing:
        raise _unprocessable(f'Unknown marketplaces: {", ".join(missing)}')
    outside = sorted(
        {p.marketplace for p in data.default_plugins}
        - set(data.allowed_marketplaces)
    )
    if outside:
        raise _unprocessable(
            'Default plugins come from marketplaces that are not allowed: '
            + ', '.join(outside)
        )
    version, current = await platform.load(store, org_id)
    try:
        data.default_plugins = platform.pin_plugins(
            data.default_plugins, current.default_plugins, found
        )
    except ValueError as err:
        raise _unprocessable(str(err)) from err
    if version is not None and data == current:
        return _config_response(
            version, current, await store.platform_config(org_id, version)
        )
    try:
        row = await store.add_platform_config(
            org_id, data.model_dump(mode='json'), auth.principal_name
        )
    except psycopg.errors.UniqueViolation as err:
        raise fastapi.HTTPException(
            status_code=409,
            detail='The configuration was changed by another request; '
            'reload it and try again',
        ) from err
    return _config_response(int(row['version']), data, row)


# --- Marketplaces ------------------------------------------------------

agent_marketplaces_router = fastapi.APIRouter(
    tags=['Agent Platform'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


async def _marketplace(
    store: harness.HarnessStore, org_id: str, slug: str
) -> dict[str, typing.Any]:
    row = await store.marketplace(org_id, slug)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Marketplace {slug!r} not found'
        )
    return row


@agent_marketplaces_router.get('/', response_model=list[MarketplaceResponse])
async def list_agent_marketplaces(
    org_id: OrgId, store: harness.Store, _: Read
) -> list[dict[str, typing.Any]]:
    """List the marketplaces of the organization with their catalogs."""
    return await store.marketplaces(org_id)


@agent_marketplaces_router.post(
    '/', status_code=201, response_model=MarketplaceResponse
)
async def create_agent_marketplace(
    org_slug: str,
    org_id: OrgId,
    data: MarketplaceCreate,
    db: graph.Pool,
    store: harness.Store,
    auth: Write,
) -> dict[str, typing.Any]:
    """Register a marketplace by git URL and sync it.

    A failed sync does not stop the registration; the response has
    ``sync_error``.

    Raises:
        409: The organization has a marketplace with this slug.

    """
    try:
        row = await store.create_marketplace(
            org_id, data.slug, str(data.url), auth.principal_name
        )
    except harness.MarketplaceExists as err:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Marketplace {data.slug!r} already exists',
        ) from err
    return await marketplaces.sync(db, store, org_slug, row)


@agent_marketplaces_router.post(
    '/{slug}/sync', response_model=MarketplaceResponse
)
async def sync_agent_marketplace(
    org_slug: str,
    org_id: OrgId,
    slug: str,
    db: graph.Pool,
    store: harness.Store,
    _: Write,
) -> dict[str, typing.Any]:
    """Read the marketplace file at the default branch head again.

    Agent versions keep the commit that they pinned. A new version, or
    a plugin given without ``sha``, pins the new head.
    """
    row = await _marketplace(store, org_id, slug)
    return await marketplaces.sync(db, store, org_slug, row)


@agent_marketplaces_router.delete('/{slug}', status_code=204)
async def delete_agent_marketplace(
    org_id: OrgId, slug: str, store: harness.Store, _: Write
) -> None:
    """Delete a marketplace.

    Pinned plugins keep the URL and the commit, so tasks of existing
    agent versions still run them.

    Raises:
        409: The newest configuration allows the marketplace.

    """
    _version, config = await platform.load(store, org_id)
    if slug in config.allowed_marketplaces:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Marketplace {slug!r} is allowed in the agent platform '
            'configuration; remove it there first',
        )
    if not await store.delete_marketplace(org_id, slug):
        raise fastapi.HTTPException(
            status_code=404, detail=f'Marketplace {slug!r} not found'
        )
