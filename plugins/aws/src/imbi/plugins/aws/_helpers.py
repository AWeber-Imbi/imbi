"""Shared utilities for the AWS capability handlers."""

from __future__ import annotations

import typing

from imbi_common.plugins.base import PluginContext

#: Integration-level option name holding the project-type-slug ->
#: path-segment overrides applied to ``${project_type_slug}``.
PROJECT_TYPE_PATH_MAP = 'project_type_path_map'


def template_vars(ctx: PluginContext) -> dict[str, str | None]:
    """Whitelisted template variables for plugin option expansion."""
    return {
        'project_slug': ctx.project_slug,
        'org_slug': ctx.org_slug,
        'team_slug': ctx.team_slug,
        'environment': ctx.environment,
        'project_id': ctx.project_id,
        'project_type_slug': _project_type_segment(ctx),
    }


def _project_type_segment(ctx: PluginContext) -> str | None:
    """First project-type slug, remapped via the integration-level
    ``project_type_path_map`` option when an entry exists.

    Lets AWS resource paths follow a naming convention that differs from
    the imbi project-type slug (e.g. type ``apis`` -> segment ``api``).
    Slugs with no mapping entry are used unchanged.
    """
    if not ctx.project_type_slugs:
        return None
    slug = ctx.project_type_slugs[0]
    overrides = ctx.integration_options.get(PROJECT_TYPE_PATH_MAP)
    if isinstance(overrides, dict):
        mapped = typing.cast('dict[str, object]', overrides).get(slug)
        if isinstance(mapped, str) and mapped.strip():
            return mapped
    return slug


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
