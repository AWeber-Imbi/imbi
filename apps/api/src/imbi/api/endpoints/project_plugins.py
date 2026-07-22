"""Read-only project capability view (``/projects/{id}/plugins/``).

The v3 assignment *editor* writes through
``/projects/{id}/integrations/``; this endpoint is the read projection
the project UI consumes to decide which capability-gated tabs
(Deployments, Logs, Configuration, ...) to surface and to render their
content.

It reports one entry per **effective** capability binding -- project-level
and project-type-level, applying the same ``effective_bindings``
resolution ``resolve_capability`` uses at execution time and filtering to
installed, enabled plugins -- so a tab shows exactly when the capability
will actually run. ``plugin_type`` carries the capability kind; a single
unified Integration (identity + deployment + lifecycle + ...) yields one
entry per enabled capability.
"""

import typing

import fastapi
import pydantic

from imbi.api.auth import permissions
from imbi.api.plugins.assignments import (
    CapabilityBinding,
    capability_enabled,
    effective_bindings,
)
from imbi.api.plugins.lifecycle import is_plugin_enabled
from imbi.common import graph
from imbi.common.plugins.base import Capability
from imbi.common.plugins.errors import PluginNotFoundError
from imbi.common.plugins.registry import get_plugin, list_plugins

project_plugins_router = fastapi.APIRouter(
    prefix='/organizations/{org_slug}/projects/{project_id}/plugins',
    tags=['Project Plugins'],
)


class PluginAssignmentResponse(pydantic.BaseModel):
    """One effective capability binding, as the project UI reads it."""

    plugin_id: str
    plugin_slug: str
    label: str
    plugin_type: str
    default: bool = False
    options: dict[str, typing.Any] = {}
    source: typing.Literal['project', 'project_type', 'merged'] = 'merged'
    #: Identity Integration whose connection powers this capability -- an
    #: explicit binding, or the serving Integration itself when it also
    #: provides identity (mirrors ``effective_identity_integration_id``).
    identity_plugin_id: str | None = None
    supports_histogram: bool = False
    supports_deployment_sync: bool = False
    supports_lifecycle_sync: bool = False
    service_name: str | None = None
    service_icon: str | None = None


def _to_response(
    binding: CapabilityBinding, kind: str, capability: Capability
) -> PluginAssignmentResponse:
    integration = binding.integration
    integration_id = str(integration.get('id') or '')
    hints = capability.hints or {}
    identity_plugin_id = binding.identity_integration_id or (
        integration_id if capability_enabled(integration, 'identity') else None
    )
    source = binding.source if binding.source != 'default_all' else 'merged'
    name = str(integration.get('name') or '')
    return PluginAssignmentResponse(
        plugin_id=integration_id,
        plugin_slug=str(integration.get('plugin') or ''),
        label=name,
        plugin_type=kind,
        default=binding.default,
        options=binding.capability_options,
        source=source,
        identity_plugin_id=identity_plugin_id,
        supports_histogram=bool(hints.get('supports_histogram')),
        supports_deployment_sync=bool(hints.get('supports_deployment_sync')),
        supports_lifecycle_sync=bool(hints.get('supports_lifecycle_sync')),
        service_name=name or None,
        service_icon=integration.get('icon'),
    )


@project_plugins_router.get('/')
async def list_project_plugins(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[PluginAssignmentResponse]:
    """Effective capability bindings for a project's UI (merged view).

    Raises:
        404: Project not found.

    """
    _ = auth
    kinds = sorted(
        {
            capability.kind
            for entry in list_plugins()
            for capability in entry.manifest.capabilities
        }
    )
    enabled: dict[str, bool] = {}
    out: list[PluginAssignmentResponse] = []
    for kind in kinds:
        try:
            bindings = await effective_bindings(db, project_id, kind)
        except LookupError as exc:
            raise fastapi.HTTPException(
                status_code=404, detail='Project not found'
            ) from exc
        for binding in bindings:
            plugin_slug = str(binding.integration.get('plugin') or '')
            try:
                entry = get_plugin(plugin_slug)
            except PluginNotFoundError:
                continue
            capability = entry.manifest.get_capability(kind)
            if capability is None:
                continue
            if plugin_slug not in enabled:
                enabled[plugin_slug] = await is_plugin_enabled(db, plugin_slug)
            if not enabled[plugin_slug]:
                continue
            out.append(_to_response(binding, kind, capability))
    return out


__all__ = ['PluginAssignmentResponse', 'project_plugins_router']
