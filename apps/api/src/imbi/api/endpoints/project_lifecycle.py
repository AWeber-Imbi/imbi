"""Project lifecycle push-sync endpoints."""

import logging
import typing

import fastapi

from imbi.api.auth import permissions
from imbi.api.domain import models
from imbi.api.plugins.lifecycle_dispatch import dispatch_lifecycle
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

project_lifecycle_router = fastapi.APIRouter(tags=['Project: Lifecycle'])


async def lifecycle_sync_for_project(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    auth: permissions.AuthContext,
) -> models.LifecycleSyncSummary:
    """Re-dispatch ``on_project_updated`` (upsert) for one project.

    Reconciles every assigned lifecycle plugin's remote with current
    Imbi state -- creating the remote when missing, updating it
    otherwise.  Each plugin's :class:`LifecycleResult` status rolls up
    into the summary: ``ok`` -> ``synced``, ``skipped`` -> ``skipped``,
    ``failed`` -> ``failed`` (with the plugin message captured in
    ``errors``).  ``dispatch_lifecycle`` already catches per-plugin
    exceptions and reports them as ``failed`` results, so this never
    raises for a single bad plugin.
    """
    summary = models.LifecycleSyncSummary(projects=1)
    invocations = await dispatch_lifecycle(
        db, project_id, org_slug, 'updated', auth
    )
    for inv in invocations:
        if inv.status == 'ok':
            summary.synced += 1
        elif inv.status == 'skipped':
            summary.skipped += 1
        else:
            summary.failed += 1
            summary.errors.append(
                models.LifecycleSyncError(
                    project_id=project_id,
                    detail=f'{inv.plugin_slug}: {inv.message or "failed"}',
                )
            )
    return summary


@project_lifecycle_router.post('/sync')
async def sync_project_lifecycle(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> models.LifecycleSyncSummary:
    """Push current Imbi state to the remote for one project.

    Re-dispatches each assigned lifecycle plugin's ``on_project_updated``
    upsert, so a sync both provisions a missing remote and updates an
    existing one.  Returns aggregate per-plugin counts; a project with
    no lifecycle plugins returns a zeroed summary.
    """
    return await lifecycle_sync_for_project(
        db, org_slug=org_slug, project_id=project_id, auth=auth
    )
