"""SonarQube lifecycle capability: delete the project with the Imbi one.

A SonarQube project only exists to receive analyses, so one whose Imbi
project has been archived or deleted is dead weight -- it keeps counting
against the licensed lines of code and shows up in every portfolio as a
project nobody will analyze again.  Both hooks delete it.

Only a project Imbi has explicitly linked is deleted: the component key
is the ``EXISTS_IN`` edge's identifier, and a project without one is
skipped.  The doctor's ``<owning-team-slug>:<project-slug>`` convention
is deliberately not used here -- it is a guess, and deleting is the one
call that cannot be taken back.  On success the hook asks the host to
drop the edge and the ``sonarqube`` dashboard link, so Imbi stops
pointing at a project that no longer exists; a later unarchive is a
fresh start, and the doctor offers to create the project again.

There is no create or update hook: SonarQube projects come into being
when the first analysis runs, or from the doctor's repair.
"""

from __future__ import annotations

from imbi.common.plugins.base import (
    LifecycleCapability,
    LifecycleResult,
    PluginContext,
    ServiceWriteback,
)
from imbi.plugins.sonarqube import client
from imbi.plugins.sonarqube.doctor import (
    LINK_KEY,
    Unconfigured,
    remediation_target,
)


class SonarQubeLifecycle(LifecycleCapability):
    """Delete the project's SonarQube project on archive and delete."""

    async def on_project_archived(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        return await self._delete(ctx, credentials)

    async def on_project_deleted(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        return await self._delete(ctx, credentials)

    async def _delete(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        """Delete the SonarQube project and drop Imbi's link to it.

        A missing ``service_url`` / token / edge is ``skipped``, not
        ``failed``: the operator's archive or delete already happened
        and there was never anything this plugin could have deleted.
        The edge check comes after :func:`remediation_target` because
        that resolves the Integration binding first, and "not bound to
        an Integration" is the better message when both are missing.  A
        project
        SonarQube no longer has is also ``skipped`` -- the outcome the
        operator wanted is in place -- but the stale edge and link are
        still removed.
        """
        try:
            base_url, api_token, key, connection = remediation_target(
                ctx, credentials
            )
        except Unconfigured as exc:
            return LifecycleResult(status='skipped', message=str(exc))
        if connection is None or not connection.identifier:
            return LifecycleResult(
                status='skipped',
                message=(
                    'The project has no EXISTS_IN edge naming a SonarQube '
                    'project; nothing to delete.'
                ),
            )
        try:
            deleted = await client.delete_project(
                base_url=base_url, api_token=api_token, key=key
            )
        except client.SonarqubeClientError as exc:
            return LifecycleResult(
                status='failed',
                message=(f'Could not delete SonarQube project {key!r}: {exc}'),
            )
        ctx.service_writeback = ServiceWriteback(
            identifier=key,
            canonical_url='',
            dashboard_links={LINK_KEY: ''},
            remove=True,
        )
        if not deleted:
            return LifecycleResult(
                status='skipped',
                message=f'SonarQube project {key!r} does not exist',
            )
        return LifecycleResult(
            status='ok', message=f'Deleted SonarQube project {key!r}'
        )
