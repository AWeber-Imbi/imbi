"""Capability resolution -- find the Integration serving a project.

``resolve_capability`` replaces v2's ``resolve_plugin``: it resolves a
single Integration for a project + capability kind, honoring the
effective-bindings + default-all rules (see
:mod:`imbi.api.plugins.assignments`) and the same ambiguity semantics as
before -- 404 when nothing is bound, 400 (``?source=<integration_slug>``)
when several are bound and none is the default.
"""

import logging
import typing

import fastapi

from imbi.api.plugins.assignments import (
    CapabilityBinding,
    effective_bindings,
)
from imbi.common import graph
from imbi.common.plugins.base import CapabilityHandler, PluginContext
from imbi.common.plugins.errors import (
    PluginNotFoundError,
    PluginUnavailableError,
)
from imbi.common.plugins.registry import RegistryEntry, get_plugin

LOGGER = logging.getLogger(__name__)


class ResolvedCapability(typing.NamedTuple):
    integration_id: str
    integration_slug: str
    plugin_slug: str
    kind: str
    entry: RegistryEntry
    capability_cls: type[CapabilityHandler]
    integration: dict[str, typing.Any]
    integration_options: dict[str, typing.Any]
    capability_options: dict[str, typing.Any]
    encrypted_credentials: dict[str, str]
    env_payloads: dict[str, dict[str, typing.Any]] | None = None
    identity_integration_id: str | None = None


def _resolved(binding: CapabilityBinding, kind: str) -> ResolvedCapability:
    integration = binding.integration
    plugin_slug = str(integration['plugin'])
    entry = get_plugin(plugin_slug)
    capability = entry.manifest.get_capability(kind)
    if capability is None:  # pragma: no cover - filtered before this point
        raise PluginNotFoundError(f'{plugin_slug}:{kind}')
    return ResolvedCapability(
        integration_id=str(integration['id']),
        integration_slug=str(integration['slug']),
        plugin_slug=plugin_slug,
        kind=kind,
        entry=entry,
        capability_cls=typing.cast(
            'type[CapabilityHandler]', capability.handler
        ),
        integration=integration,
        integration_options=integration.get('options') or {},
        capability_options=binding.capability_options,
        encrypted_credentials=integration.get('encrypted_credentials') or {},
        env_payloads=binding.env_payloads or None,
        identity_integration_id=binding.identity_integration_id,
    )


async def _loaded_and_enabled(
    db: graph.Graph, binding: CapabilityBinding, kind: str
) -> bool:
    """True when the binding's plugin is loaded, declares ``kind``, and its
    ``PluginRegistration`` is enabled."""
    from imbi.api.plugins.lifecycle import is_plugin_enabled

    plugin_slug = binding.integration.get('plugin')
    if not plugin_slug:
        return False
    try:
        entry = get_plugin(str(plugin_slug))
    except PluginNotFoundError:
        return False
    if entry.manifest.get_capability(kind) is None:
        return False
    return await is_plugin_enabled(db, str(plugin_slug))


async def _candidates(
    db: graph.Graph, project_id: str, kind: str
) -> list[CapabilityBinding]:
    try:
        bindings = await effective_bindings(db, project_id, kind)
    except LookupError as exc:
        raise fastapi.HTTPException(
            status_code=404, detail='Project not found'
        ) from exc
    out: list[CapabilityBinding] = []
    for binding in bindings:
        if await _loaded_and_enabled(db, binding, kind):
            out.append(binding)
    return out


async def resolve_capability(
    db: graph.Graph,
    project_id: str,
    kind: str,
    source: str | None,
) -> ResolvedCapability:
    """Resolve the Integration serving ``project_id`` for ``kind``.

    Raises:
        fastapi.HTTPException 404: project missing, or nothing bound.
        fastapi.HTTPException 400: several bound and no default; caller
            must pass ``source`` = Integration slug.
    """
    candidates = await _candidates(db, project_id, kind)
    if not candidates:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'No integration provides the {kind!r} capability for this '
                f'project'
            ),
        )
    if source:
        # ``source`` disambiguates when several integrations serve a
        # capability. The UI identifies integrations by id; a slug is also
        # accepted for URL/CLI use. Both are unique on Integration.
        chosen = next(
            (
                b
                for b in candidates
                if source
                in (b.integration.get('slug'), b.integration.get('id'))
            ),
            None,
        )
        if chosen is None:
            raise fastapi.HTTPException(
                status_code=404,
                detail=(
                    f'Integration {source!r} does not provide {kind!r} for '
                    f'this project'
                ),
            )
    elif len(candidates) == 1:
        chosen = candidates[0]
    else:
        project_defaults = [
            b for b in candidates if b.source == 'project' and b.default
        ]
        type_defaults = [
            b for b in candidates if b.source == 'project_type' and b.default
        ]
        defaults = project_defaults or type_defaults
        if not defaults:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    'Multiple integrations provide this capability; specify '
                    '?source=<integration_slug>'
                ),
            )
        chosen = defaults[0]
    try:
        return _resolved(chosen, kind)
    except PluginNotFoundError as exc:
        raise PluginUnavailableError(
            str(chosen.integration.get('plugin'))
        ) from exc


async def resolve_all_capabilities(
    db: graph.Graph,
    project_id: str,
    kind: str,
) -> list[ResolvedCapability]:
    """Return every Integration bound to ``project_id`` for ``kind``.

    Fan-out sibling of :func:`resolve_capability` for call sites (e.g.
    lifecycle dispatch, analysis) that invoke every bound Integration.
    Returns an empty list when the project exists but nothing is bound;
    raises 404 only when the project itself is missing.
    """
    candidates = await _candidates(db, project_id, kind)
    resolved: list[ResolvedCapability] = []
    for binding in candidates:
        try:
            resolved.append(_resolved(binding, kind))
        except PluginNotFoundError:
            LOGGER.warning(
                'Skipping unresolvable integration %r during %s fan-out',
                binding.integration.get('slug'),
                kind,
            )
    return resolved


def build_plugin_context(
    resolved: ResolvedCapability,
    *,
    project_id: str,
    project_slug: str,
    org_slug: str,
    **extra: typing.Any,
) -> PluginContext:
    """Build a :class:`PluginContext` from a resolved capability.

    Populates ``integration_slug``, ``integration_options``, and
    ``capability_options`` from the resolution; callers pass any
    additional context fields as keyword arguments.
    """
    return PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        integration_slug=resolved.integration_slug,
        integration_options=resolved.integration_options,
        capability_options=resolved.capability_options,
        assignment_options=resolved.capability_options,
        **extra,
    )
