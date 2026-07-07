"""Non-admin plugin metadata endpoints.

Exposes the static plugin manifest (integration-level options +
credentials, plus the capability catalog) so project editors with
``project:write`` can render a typed Integration form without needing
the admin ``admin:plugins:read`` permission. Only schema metadata is
returned — nothing about install state, package details, or per-org
configuration.
"""

import typing

import fastapi
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.auth import permissions

plugins_router = fastapi.APIRouter(tags=['Plugins'])


@plugins_router.get('/plugins/{slug}/manifest')
async def get_plugin_manifest(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> dict[str, typing.Any]:
    """Return a plugin's manifest for Integration-form rendering.

    Gated on authentication only — the manifest is static metadata
    shipped in the plugin's Python package and is not sensitive.
    Project editors need this to render a typed Integration options /
    credentials / capabilities form.
    """
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    return entry.manifest.model_dump()
