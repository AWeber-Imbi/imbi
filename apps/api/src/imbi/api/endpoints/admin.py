"""Admin settings endpoint for reference data."""

import logging
import typing

import fastapi
import pydantic

from imbi.api import models
from imbi.api.auth import permissions
from imbi.common import graph

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
    db: graph.Pool,
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
    all_permissions = await db.match(models.Permission, order_by='name')

    return AdminSettings(
        permissions=all_permissions,
        oauth_provider_types=['google', 'github', 'oidc'],
        auth_methods=['jwt', 'api_key'],
        auth_types=['oauth', 'password'],
    )
