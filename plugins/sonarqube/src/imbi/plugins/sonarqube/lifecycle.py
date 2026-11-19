"""SonarQube lifecycle capability: delete the project with the Imbi one.

A SonarQube project only exists to receive analyses, so one whose Imbi
project has been archived or deleted is dead weight -- it keeps counting
against the licensed lines of code and shows up in every portfolio as a
project nobody will analyze again.  Both hooks delete it.

Only a project Imbi has explicitly linked is deleted: the component key
is the ``EXISTS_IN`` edge's identifier, and a project without one is
skipped.  The doctor's ``<owning-team-slug>:<project-slug>`` convention
is never used to find the key -- it is a guess, and deleting is the one
call that cannot be taken back.  It is used as a check: the linked key
must equal it, because any project writer can link any key (#775).
On success the hook asks the host to
drop the edge and the ``sonarqube`` dashboard link, so Imbi stops
pointing at a project that no longer exists; a later unarchive is a
fresh start, and the doctor offers to create the project again.

There is no create or update hook: SonarQube projects come into being
when the first analysis runs, or from the doctor's repair.
"""

from __future__ import annotations

import logging

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

LOGGER = logging.getLogger(__name__)


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

        A key that is not ``<owning-team-slug>:<project-slug>``, or
        that another Imbi project also links, is ``skipped`` and not
        deleted (#775).
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
        expected = f'{ctx.team_slug}:{ctx.project_slug}'
        if not ctx.team_slug or key != expected:
            LOGGER.warning(
                'Not deleting SonarQube project %r for project %s: the '
                'key is not %r',
                key,
                ctx.project_id,
                expected,
            )
            return LifecycleResult(
                status='skipped',
                message=(
                    f'Not deleting SonarQube project {key!r}: only the '
                    f'project key {expected!r} is deleted.'
                ),
            )
        if ctx.resolve_identifier_holder is None:
            return LifecycleResult(
                status='skipped',
                message=(
                    f'Cannot check if another project links SonarQube '
                    f'project {key!r}; not deleting it.'
                ),
            )
        holder = await ctx.resolve_identifier_holder(key)
        if holder is not None:
            return LifecycleResult(
                status='skipped',
                message=(
                    f'Not deleting SonarQube project {key!r}: project '
                    f'{holder!r} also links it.'
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
