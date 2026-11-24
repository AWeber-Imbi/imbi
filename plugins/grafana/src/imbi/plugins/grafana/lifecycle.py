"""Grafana lifecycle capability: link each project to its alert rules.

Grafana has no project resource to create. The hooks write the
``EXISTS_IN`` edge whose identifier the gateway matches against the
label in each alert delivery, and the ``grafana`` link to the alert
rules that carry that label. Archive is a no-op; delete removes the
edge and the link.
"""

from __future__ import annotations

from imbi.common.plugins.base import (
    LifecycleCapability,
    LifecycleResult,
    PluginContext,
)
from imbi.plugins.grafana import links


class GrafanaLifecycle(LifecycleCapability):
    """Write (or refresh) the project's edge to the Grafana integration."""

    async def on_project_archived(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        del ctx, credentials
        return LifecycleResult(
            status='skipped', message='Grafana has no archive concept'
        )

    async def on_project_created(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        del credentials
        return self._link(ctx)

    async def on_project_updated(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        del credentials
        return self._link(ctx)

    async def on_project_deleted(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        del credentials
        if links.connection(ctx) is None:
            return LifecycleResult(
                status='skipped', message='No Grafana link to remove'
            )
        try:
            expected = links.writeback(ctx, links.identifier(ctx))
        except links.GrafanaConfigError as exc:
            return LifecycleResult(status='failed', message=str(exc))
        ctx.service_writeback = expected.model_copy(update={'remove': True})
        return LifecycleResult(
            status='ok',
            message=f'Removed the Grafana link {expected.identifier!r}',
        )

    @staticmethod
    def _link(ctx: PluginContext) -> LifecycleResult:
        value = links.identifier(ctx)
        try:
            expected = links.writeback(ctx, value)
        except links.GrafanaConfigError as exc:
            return LifecycleResult(status='failed', message=str(exc))
        if links.matches(ctx, expected):
            return LifecycleResult(
                status='skipped',
                message=f'Already linked as {links.label(ctx)}={value!r}',
            )
        ctx.service_writeback = expected
        verb = 'Refreshed' if links.connection(ctx) else 'Linked'
        return LifecycleResult(
            status='ok',
            message=f'{verb} the Grafana link {links.label(ctx)}={value!r}',
            artifacts={'identifier': value, 'label': links.label(ctx)},
        )
