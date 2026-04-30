"""Admin endpoints for the local-auth (password login) toggle."""

from __future__ import annotations

import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api.auth import local_auth, permissions

LOGGER = logging.getLogger(__name__)

local_auth_router = fastapi.APIRouter(
    prefix='/admin/local-auth',
    tags=['Admin', 'Local Authentication'],
)


class LocalAuthRead(pydantic.BaseModel):
    """Response model for the local-auth config."""

    model_config = pydantic.ConfigDict(extra='forbid')

    enabled: bool
    updated_at: datetime.datetime | None


class LocalAuthWrite(pydantic.BaseModel):
    """Request body for ``PUT /admin/local-auth``."""

    model_config = pydantic.ConfigDict(extra='forbid')

    enabled: bool


@local_auth_router.get('', response_model=LocalAuthRead)
async def get_local_auth(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('auth_providers:read')),
    ],
) -> LocalAuthRead:
    """Return the current local-auth config (defaults to enabled)."""
    config = await local_auth.get_config(db)
    return LocalAuthRead(
        enabled=config.enabled,
        updated_at=config.updated_at,
    )


@local_auth_router.put('', response_model=LocalAuthRead)
async def set_local_auth(
    data: LocalAuthWrite,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('auth_providers:write')
        ),
    ],
) -> LocalAuthRead:
    """Persist the local-auth toggle."""
    config = await local_auth.set_enabled(db, data.enabled)
    LOGGER.info(
        'Local auth %s by %s',
        'enabled' if data.enabled else 'disabled',
        auth.principal_name,
    )
    return LocalAuthRead(
        enabled=config.enabled,
        updated_at=config.updated_at,
    )
