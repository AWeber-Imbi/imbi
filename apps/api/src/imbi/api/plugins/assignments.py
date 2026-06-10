"""Plugin assignment validation and shared response helpers."""

import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins import PluginType
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.domain import models
from imbi_api.plugins import parse_options


class PluginAssignmentRow(typing.TypedDict):
    plugin_id: str
    plugin_type: PluginType
    default: bool
    options: dict[str, typing.Any]
    identity_plugin_id: typing.NotRequired[str | None]
    env_payloads: typing.NotRequired[dict[str, dict[str, typing.Any]]]


def validate_one_default_per_plugin_type(
    assignments: list[PluginAssignmentRow],
) -> None:
    """Ensure exactly one default per plugin type in the assignment list.

    Raises:
        ValueError: If a plugin type has 0 or >1 defaults.
    """
    by_plugin_type: dict[str, list[bool]] = {}
    for row in assignments:
        by_plugin_type.setdefault(row['plugin_type'], []).append(
            row['default']
        )

    for plugin_type, defaults in by_plugin_type.items():
        count = sum(1 for d in defaults if d)
        if count == 0:
            raise ValueError(
                f'Plugin type {plugin_type!r} has no default plugin assignment'
            )
        if count > 1:
            raise ValueError(
                f'Plugin type {plugin_type!r} has {count} default plugin'
                f' assignments; exactly one is required'
            )


async def validate_identity_plugin_ids(
    db: graph.Graph,
    org_slug: str,
    identity_plugin_ids: list[str],
) -> None:
    """Validate every supplied id is an identity-type plugin in registry.

    The lookup is scoped to ``org_slug`` so an admin in one org can't
    bind an assignment to an identity plugin owned by another org by
    guessing its id.  Raises ``HTTPException(400)`` listing every
    invalid id (not found, not loaded, wrong type, or out-of-org).
    """
    if not identity_plugin_ids:
        return
    query: typing.LiteralString = (
        'UNWIND {ids} AS pid '
        'OPTIONAL MATCH (p:Plugin {{id: pid}})'
        '<-[:HAS_PLUGIN]-(:ThirdPartyService)'
        '-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}}) '
        'RETURN pid AS id, p.plugin_slug AS slug'
    )
    rows = await db.execute(
        query,
        {'ids': identity_plugin_ids, 'org_slug': org_slug},
        ['id', 'slug'],
    )
    bad: list[str] = []
    for row in rows:
        pid = str(graph.parse_agtype(row['id']))
        slug = graph.parse_agtype(row.get('slug'))
        if not slug:
            bad.append(f'{pid} (plugin not found)')
            continue
        try:
            entry = get_plugin(str(slug))
        except PluginNotFoundError:
            bad.append(f'{pid} ({slug!r} not loaded)')
            continue
        if entry.manifest.plugin_type != 'identity':
            bad.append(
                f'{pid} ({slug!r} is plugin_type='
                f'{entry.manifest.plugin_type!r}, expected identity)'
            )
    if bad:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Invalid identity_plugin_id values: ' + ', '.join(bad),
        )


def coerce_identity_plugin_id(raw: typing.Any) -> str | None:
    """Coerce a graph-stored identity_plugin_id to ``str | None``.

    Treats empty strings and non-string types as missing.
    """
    return str(raw) if isinstance(raw, str) and raw else None


def build_assignment_response(
    plugin: dict[str, typing.Any],
    edge: dict[str, typing.Any],
    source: typing.Literal['project', 'project_type', 'merged'],
    service: dict[str, typing.Any] | None = None,
) -> models.PluginAssignmentResponse:
    """Build a PluginAssignmentResponse from parsed plugin/edge dicts."""
    supports_histogram = False
    supports_deployment_sync = False
    supports_lifecycle_sync = False
    try:
        manifest = get_plugin(plugin['plugin_slug']).manifest
        supports_histogram = bool(manifest.supports_histogram)
        supports_deployment_sync = bool(
            getattr(manifest, 'supports_deployment_sync', False)
        )
        supports_lifecycle_sync = bool(
            getattr(manifest, 'supports_lifecycle_sync', False)
        )
    except PluginNotFoundError:
        pass
    return models.PluginAssignmentResponse(
        plugin_id=plugin['id'],
        plugin_slug=plugin['plugin_slug'],
        label=plugin['label'],
        # Transitional: read the new ``plugin_type`` edge property,
        # falling back to the legacy ``tab`` name until the rename
        # migration has run. Drop the ``tab`` fallback afterward.
        plugin_type=edge.get('plugin_type', edge.get('tab', 'configuration')),
        default=bool(edge.get('default', False)),
        options=parse_options(edge.get('options')),
        source=source,
        identity_plugin_id=coerce_identity_plugin_id(
            edge.get('identity_plugin_id')
        ),
        env_payloads=_parse_env_payloads(edge.get('env_payloads')),
        supports_histogram=supports_histogram,
        supports_deployment_sync=supports_deployment_sync,
        supports_lifecycle_sync=supports_lifecycle_sync,
        service_name=(service or {}).get('name'),
        service_icon=(service or {}).get('icon'),
    )


def _parse_env_payloads(
    raw: typing.Any,
) -> dict[str, dict[str, typing.Any]]:
    """Parse a USES_PLUGIN edge ``env_payloads`` value to a dict.

    Stored JSON-encoded on the AGE edge (the underlying property store
    can't hold nested property maps).  Returns an empty dict when
    missing, malformed, or shaped wrong -- malformed env_payloads
    should not bring down deployment dispatch.
    """
    parsed = parse_options(raw)
    return {
        slug: payload
        for slug, payload in parsed.items()
        if isinstance(payload, dict)
    }
