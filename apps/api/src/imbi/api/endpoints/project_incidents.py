"""Project incidents plugin endpoints."""

import datetime
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins import decrypt_integration_credentials
from imbi_common.plugins.base import (
    IncidentResult,
    IncidentsCapability,
    PluginContext,
)
from imbi_common.plugins.errors import CursorExpiredError

from imbi_api.auth import permissions
from imbi_api.endpoints._helpers import (
    lookup_project_links,
    lookup_project_slugs,
)
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.resolution import resolve_capability

LOGGER = logging.getLogger(__name__)

project_incidents_router = fastapi.APIRouter(tags=['Project: Incidents'])


@project_incidents_router.get('/')
async def list_incidents(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    start_time: str | None = fastapi.Query(default=None),
    end_time: str | None = fastapi.Query(default=None),
    status: list[str] = fastapi.Query(  # noqa: B008
        default_factory=list,
    ),
    cursor: str | None = fastapi.Query(default=None),
    limit: int = fastapi.Query(default=100, ge=1, le=1000),
) -> IncidentResult:
    """List the project's incidents via the assigned incidents plugin.

    Live-queries the incident-management system (e.g. PagerDuty) for the
    project's service over ``[start_time, end_time]`` (default: the last
    7 days), optionally filtered by ``status`` (a repeated query param:
    ``?status=triggered&status=acknowledged``). Read-only -- there is no
    local incident store; the source system stays authoritative.
    """
    del auth  # required for authorization; not used in the body
    resolved = await resolve_capability(db, project_id, 'incidents', source)

    now = datetime.datetime.now(datetime.UTC)
    try:
        start_dt = (
            datetime.datetime.fromisoformat(start_time)
            if start_time
            else now - datetime.timedelta(days=7)
        )
        end_dt = datetime.datetime.fromisoformat(end_time) if end_time else now
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid datetime format: {exc}',
        ) from exc
    # ``fromisoformat`` accepts naive timestamps; coerce to UTC so plugin
    # handlers always receive aware datetimes (matches project_logs.py).
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=datetime.UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=datetime.UTC)
    if start_dt > end_dt:
        raise fastapi.HTTPException(
            status_code=400,
            detail='start_time must be less than or equal to end_time',
        )

    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        assignment_options=resolved.capability_options,
        integration_options=resolved.integration_options,
        capability_options=resolved.capability_options,
        # The plugin resolves its remote service from a project link
        # (e.g. ``pagerduty-service``), so populate the link map.
        project_links=await lookup_project_links(db, project_id),
    )
    credentials = decrypt_integration_credentials(
        resolved.encrypted_credentials
    )
    if not credentials:
        raise fastapi.HTTPException(
            status_code=503,
            detail='No credentials configured for this integration',
        )

    handler = typing.cast(IncidentsCapability, resolved.capability_cls())
    try:
        return await call_with_timeout(
            handler.list_incidents(
                ctx,
                credentials,
                start_time=start_dt,
                end_time=end_dt,
                statuses=list(status) or None,
                cursor=cursor,
                limit=limit,
            )
        )
    except CursorExpiredError as exc:
        raise fastapi.HTTPException(
            status_code=409,
            detail={'error': 'cursor_expired', 'message': str(exc)},
        ) from exc
