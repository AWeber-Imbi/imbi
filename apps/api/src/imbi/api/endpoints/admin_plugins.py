"""Admin plugin management endpoints."""

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
from imbi_api.plugins import catalog, installer
from imbi_api.plugins.lifecycle import (
    get_enabled_map,
    get_unavailable_slugs,
    set_plugin_enabled,
)

admin_plugins_router = fastapi.APIRouter(tags=['Admin: Plugins'])


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
    return {
        'installed': [
            _serialize(e, enabled_map.get(e.manifest.slug, False))
            for e in list_plugins()
        ],
        'unavailable': get_unavailable_slugs(),
    }


@admin_plugins_router.get('/plugins/catalog')
async def list_plugin_catalog(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> list[catalog.CatalogEntry]:
    """List the plugin catalog with install status."""
    return catalog.list_catalog_entries()


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


@admin_plugins_router.post('/plugins/install')
async def install_plugin(
    body: dict[str, str | None],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Install a plugin package at runtime."""
    package = body.get('package')
    if not package:
        raise fastapi.HTTPException(
            status_code=400, detail='package is required'
        )
    version = body.get('version')
    try:
        result = await installer.install_package(package, version)
    except installer.InstallError as e:
        raise fastapi.HTTPException(status_code=400, detail=str(e)) from e
    return {
        'loaded': result.loaded,
        'errors': result.errors,
        'skipped': result.skipped,
    }


@admin_plugins_router.delete('/plugins/installed/{package}', status_code=204)
async def uninstall_plugin(
    package: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> None:
    """Uninstall a plugin package at runtime."""
    try:
        await installer.uninstall_package(package)
    except installer.InstallError as e:
        raise fastapi.HTTPException(status_code=400, detail=str(e)) from e
