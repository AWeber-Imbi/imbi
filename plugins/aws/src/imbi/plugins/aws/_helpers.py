"""Shared utilities for the AWS capability handlers."""

from __future__ import annotations

from imbi_common.plugins.base import PluginContext


def template_vars(ctx: PluginContext) -> dict[str, str | None]:
    """Whitelisted template variables for plugin option expansion."""
    return {
        'project_slug': ctx.project_slug,
        'org_slug': ctx.org_slug,
        'team_slug': ctx.team_slug,
        'environment': ctx.environment,
        'project_id': ctx.project_id,
    }


def integration_region(ctx: PluginContext) -> str | None:
    """The Integration-level ``region`` option, shared by every AWS
    capability (:attr:`PluginContext.integration_options`)."""
    region = ctx.integration_options.get('region')
    return str(region) if region else None


def capability_timeout(
    ctx: PluginContext, *, default: float, key: str = 'timeout_seconds'
) -> float:
    """A capability-scoped numeric option
    (:attr:`PluginContext.capability_options`)."""
    raw = ctx.capability_options.get(key)
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
