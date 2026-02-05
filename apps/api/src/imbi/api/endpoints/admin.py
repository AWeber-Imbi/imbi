"""Admin settings endpoint for reference data."""

import logging
import typing

import fastapi
import pydantic
from imbi_common import models, neo4j

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

admin_router = fastapi.APIRouter(prefix='/admin', tags=['Admin'])


class AdminSettings(pydantic.BaseModel):
    """Reference data for the admin UI."""

    permissions: list[models.Permission]
    oauth_provider_types: list[str]
    auth_methods: list[str]
    auth_types: list[str]


@admin_router.get('/settings', response_model=AdminSettings)
async def get_admin_settings(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> AdminSettings:
    """Return reference data for admin UI sections.

    Returns all available permissions, OAuth provider types, and
    authentication method metadata. Requires authentication but no
    specific permission since this is read-only metadata.
    """
    all_permissions: list[models.Permission] = []
    async for perm in neo4j.fetch_nodes(models.Permission, order_by='name'):
        all_permissions.append(perm)

    return AdminSettings(
        permissions=all_permissions,
        oauth_provider_types=['google', 'github', 'oidc'],
        auth_methods=['jwt', 'api_key'],
        auth_types=['oauth', 'password'],
    )
