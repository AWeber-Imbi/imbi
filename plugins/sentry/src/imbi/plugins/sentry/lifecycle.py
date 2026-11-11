"""Sentry lifecycle capability: create the Sentry project with the Imbi one.

The Sentry project slug is the Imbi project slug and is written to the
``EXISTS_IN`` edge, so the gateway routes Sentry webhooks to the
project. There is no delete hook: deleting the Imbi project drops its
edge and links, and the Sentry project keeps its issue history.
"""

from __future__ import annotations

import typing

from imbi.common.plugins.base import (
    LifecycleCapability,
    LifecycleResult,
    PluginContext,
)
from imbi.plugins.sentry import client


async def find_or_create(
    ctx: PluginContext, s: client.Settings, slug: str
) -> tuple[dict[str, typing.Any], bool]:
    """Return the Sentry project ``slug`` and whether it was created.

    Raises :class:`client.SentryClientError` when it is absent and cannot
    be created.
    """
    project = await client.get_project(s, slug)
    team = client.sentry_team(ctx)
    if project is not None:
        if not client.may_link(project, team):
            raise client.SentryClientError(
                f'Sentry project {slug!r} exists and is owned only by other '
                f'teams ({", ".join(client.team_slugs(project))}); refusing '
                'to link it.'
            )
        return project, False
    if team is None:
        raise client.SentryClientError(
            'The project has no owning team to map to a Sentry team.'
        )
    project = await client.create_project(
        s, team, slug, ctx.project_name or slug
    )
    return project, True


class SentryLifecycle(LifecycleCapability):
    """Create (or link) the project's Sentry project."""

    async def on_project_archived(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        del ctx, credentials
        return LifecycleResult(
            status='skipped', message='Sentry has no archive concept'
        )

    async def on_project_created(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        try:
            s = client.settings(ctx, credentials)
            project, created = await find_or_create(ctx, s, ctx.project_slug)
        except client.SentryClientError as exc:
            return LifecycleResult(status='failed', message=str(exc))
        ctx.service_writeback = client.writeback(ctx, s, project)
        verb = 'Created' if created else 'Linked existing'
        return LifecycleResult(
            status='ok',
            message=f'{verb} Sentry project {project["slug"]!r}',
            artifacts={'project_id': str(project['id'])},
        )
