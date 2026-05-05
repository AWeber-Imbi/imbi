"""Admin plugin management endpoints."""

import importlib.metadata
import typing

import fastapi
import pydantic
from imbi_common import graph
from imbi_common.plugins.errors import (
    PluginNotFoundError,
)
from imbi_common.plugins.registry import (
    RegistryEntry,
    get_plugin,
    list_plugins,
)

from imbi_api.auth import permissions
from imbi_api.plugins.lifecycle import (
    get_enabled_map,
    set_plugin_enabled,
)

admin_plugins_router = fastapi.APIRouter(
    prefix='/admin', tags=['Admin: Plugins']
)


def _serialize(entry: RegistryEntry, enabled: bool) -> dict[str, typing.Any]:
    return {
        'slug': entry.manifest.slug,
        'name': entry.manifest.name,
        'description': entry.manifest.description,
        'api_version': entry.manifest.api_version,
        'auth_type': entry.manifest.auth_type,
        'cacheable': entry.manifest.cacheable,
        'enabled': enabled,
        'package_name': entry.package_name,
        'package_version': entry.package_version,
        'docs_url': getattr(entry.manifest, 'docs_url', None),
        'supported_tabs': [entry.manifest.plugin_type],
        'options': [o.model_dump() for o in entry.manifest.options],
        'credentials': [c.model_dump() for c in entry.manifest.credentials],
    }


def _placeholder(package_name: str) -> dict[str, typing.Any]:
    return {
        'slug': package_name,
        'name': package_name,
        'description': '',
        'api_version': 0,
        'auth_type': 'api_token',
        'cacheable': False,
        'enabled': False,
        'package_name': package_name,
        'package_version': None,
        'docs_url': None,
        'supported_tabs': [],
        'options': [],
        'credentials': [],
    }


@admin_plugins_router.get('/plugins')
async def list_installed_plugins(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """List installed plugins with enabled state.

    The UI splits this list by ``enabled`` — disabled rows render as
    "Catalog" entries that admins can promote, enabled rows render as
    "Installed" entries available for assignment.
    """
    enabled_map = await get_enabled_map(db)
    registered = list_plugins()
    known_packages = {e.package_name for e in registered}

    installed = [
        _serialize(e, enabled_map.get(e.manifest.slug, False))
        for e in registered
    ]

    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name', '') or ''
        if (
            name.lower().startswith('imbi-plugin-')
            and name not in known_packages
        ):
            installed.append(_placeholder(name))

    return {'installed': installed}


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
) -> dict[str, typing.Any]:
    """Get details for a single installed plugin."""
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    enabled_map = await get_enabled_map(db)
    payload = _serialize(entry, enabled_map.get(entry.manifest.slug, False))
    payload['data_types'] = [d.model_dump() for d in entry.manifest.data_types]
    return payload


class _EnablePayload(pydantic.BaseModel):
    enabled: bool


@admin_plugins_router.patch('/plugins/{slug}')
async def update_installed_plugin(
    slug: str,
    body: _EnablePayload,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Toggle a plugin between enabled and disabled."""
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    await set_plugin_enabled(db, slug, body.enabled)
    payload = _serialize(entry, body.enabled)
    payload['data_types'] = [d.model_dump() for d in entry.manifest.data_types]
    return payload
