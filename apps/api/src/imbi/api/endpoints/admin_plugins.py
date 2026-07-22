"""Admin plugin management endpoints."""

import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import (
    RegistryEntry,
    get_plugin,
    list_plugins,
)

from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.endpoints import plugin_edges as _plugin_edges
from imbi_api.plugins.lifecycle import (
    get_enabled_map,
    set_plugin_enabled,
)

LOGGER = logging.getLogger(__name__)

admin_plugins_router = fastapi.APIRouter(
    prefix='/admin', tags=['Admin: Plugins']
)


def _build_response(
    entry: RegistryEntry, enabled: bool
) -> models.InstalledPluginResponse:
    """Build an ``InstalledPluginResponse`` from a registry entry.

    The manifest is serialized as pure data (``Capability.handler`` is
    excluded by the manifest itself) plus package identity and
    registration state.
    """
    payload = entry.manifest.model_dump()
    payload['package_name'] = entry.package_name
    payload['package_version'] = entry.package_version
    payload['enabled'] = enabled
    return models.InstalledPluginResponse(**payload)


@admin_plugins_router.get('/plugins')
async def list_installed_plugins(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> list[models.InstalledPluginResponse]:
    """List installed plugin packages with their enabled state."""
    _ = auth
    enabled_map = await get_enabled_map(db)
    return [
        _build_response(entry, enabled_map.get(entry.manifest.slug, False))
        for entry in list_plugins()
    ]


@admin_plugins_router.get('/plugins/{slug}')
async def get_installed_plugin(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> models.InstalledPluginResponse:
    """Get details for a single installed plugin package."""
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    enabled_map = await get_enabled_map(db)
    return _build_response(entry, enabled_map.get(entry.manifest.slug, False))


@admin_plugins_router.put('/plugins/{slug}/registration')
async def update_plugin_registration(
    slug: str,
    body: models.PluginRegistrationUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> models.InstalledPluginResponse:
    """Enable or disable an installed plugin package."""
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    await set_plugin_enabled(db, slug, body.enabled)
    return _build_response(entry, body.enabled)


@admin_plugins_router.get('/plugins/{slug}/edges')
async def list_plugin_edges(
    slug: str,
    rel_type: str,
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, list[_plugin_edges.EdgeResponse]]:
    """Bulk-fetch every Environment-anchored edge of ``rel_type`` for an org.

    Returns ``{env_slug: [edges]}`` for every environment in ``org_slug``,
    including environments with no outgoing edge (empty list). Used by
    the plugin admin UI to render the per-org edge mapping table without
    one HTTP request per environment.
    """
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    declares = any(
        edge.name == rel_type and 'Environment' in edge.from_labels
        for edge in entry.manifest.edge_labels
    )
    if not declares:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Plugin {slug!r} does not declare Environment edge '
                f'{rel_type!r}'
            ),
        )
    return await _plugin_edges.list_org_environment_edges(
        db=db, rel_type=rel_type, org_slug=org_slug
    )
