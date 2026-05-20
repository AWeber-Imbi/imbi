"""Non-admin plugin metadata endpoints.

Exposes the static plugin manifest (option + credential schemas) so
project editors with ``project:write`` can render a typed form for
per-project plugin option overrides without needing the admin
``admin:plugins:read`` permission. Only schema metadata is returned —
nothing about install state, package details, or per-org overrides.
"""

import typing

import fastapi
import pydantic
from imbi_common.plugins.base import CredentialField, PluginOption
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.auth import permissions

plugins_router = fastapi.APIRouter(tags=['Plugins'])


class PluginManifestResponse(pydantic.BaseModel):
    """Minimal plugin manifest for option-editor rendering."""

    slug: str
    name: str
    description: str | None = None
    plugin_type: str
    options: list[PluginOption]
    credentials: list[CredentialField]


@plugins_router.get('/plugins/{slug}/manifest')
async def get_plugin_manifest(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> PluginManifestResponse:
    """Return the option and credential schemas for a plugin.

    Gated on authentication only — the manifest is static metadata
    shipped in the plugin's Python package and is not sensitive.
    Project editors need this to render a typed form for per-project
    option overrides on the ``USES_PLUGIN`` edge.
    """
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    manifest = entry.manifest
    return PluginManifestResponse(
        slug=manifest.slug,
        name=manifest.name,
        description=manifest.description,
        plugin_type=manifest.plugin_type,
        options=list(manifest.options),
        credentials=list(manifest.credentials),
    )
