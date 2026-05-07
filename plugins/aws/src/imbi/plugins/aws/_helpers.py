"""Shared utilities for the AWS data plugins."""

from __future__ import annotations

from imbi_common.plugins.base import PluginContext


def template_vars(ctx: PluginContext) -> dict[str, str | None]:
    """Whitelisted template variables for plugin option expansion."""
    return {
        'project_slug': ctx.project_slug,
        'org_slug': ctx.org_slug,
        'environment': ctx.environment,
        'project_id': ctx.project_id,
    }


def assignment_region(ctx: PluginContext) -> str | None:
    region = ctx.assignment_options.get('region')
    return str(region) if region else None


def assignment_timeout(
    ctx: PluginContext, *, default: float, key: str = 'timeout_seconds'
) -> float:
    raw = ctx.assignment_options.get(key)
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
