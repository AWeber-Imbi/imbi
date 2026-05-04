"""Admin plugin management endpoints."""

import typing

import fastapi
from imbi_common.plugins.errors import (
    PluginNotFoundError,
)
from imbi_common.plugins.registry import (
    get_plugin,
    list_plugins,
)

from imbi_api.auth import permissions
from imbi_api.plugins import catalog, installer
from imbi_api.plugins.lifecycle import get_unavailable_slugs

admin_plugins_router = fastapi.APIRouter(tags=['Admin: Plugins'])


@admin_plugins_router.get('/plugins')
async def list_installed_plugins(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """List installed plugins and unavailable slugs."""
    entries = list_plugins()
    installed = [
        {
            'slug': e.manifest.slug,
            'name': e.manifest.name,
            'plugin_type': e.manifest.plugin_type,
            'api_version': e.manifest.api_version,
            'package': e.package_name,
            'version': e.package_version,
        }
        for e in entries
    ]
    return {
        'installed': installed,
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
    return {
        'slug': entry.manifest.slug,
        'name': entry.manifest.name,
        'description': entry.manifest.description,
        'plugin_type': entry.manifest.plugin_type,
        'api_version': entry.manifest.api_version,
        'cacheable': entry.manifest.cacheable,
        'package': entry.package_name,
        'version': entry.package_version,
        'options': [o.model_dump() for o in entry.manifest.options],
        'credentials': [c.model_dump() for c in entry.manifest.credentials],
        'data_types': [d.model_dump() for d in entry.manifest.data_types],
    }


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
