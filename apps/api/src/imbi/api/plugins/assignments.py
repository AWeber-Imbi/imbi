"""Plugin assignment validation and shared response helpers."""

import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.domain import models
from imbi_api.plugins import parse_options


class PluginAssignmentRow(typing.TypedDict):
    plugin_id: str
    tab: typing.Literal['configuration', 'logs']
    default: bool
    options: dict[str, typing.Any]
    identity_plugin_id: typing.NotRequired[str | None]


def validate_one_default_per_tab(
    assignments: list[PluginAssignmentRow],
) -> None:
    """Ensure exactly one default per tab in the assignment list.

    Raises:
        ValueError: If a tab has 0 or >1 defaults.
    """
    by_tab: dict[str, list[bool]] = {}
    for row in assignments:
        by_tab.setdefault(row['tab'], []).append(row['default'])

    for tab, defaults in by_tab.items():
        count = sum(1 for d in defaults if d)
        if count == 0:
            raise ValueError(f'Tab {tab!r} has no default plugin assignment')
        if count > 1:
            raise ValueError(
                f'Tab {tab!r} has {count} default plugin assignments;'
                f' exactly one is required'
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


def build_assignment_response(
    plugin: dict[str, typing.Any],
    edge: dict[str, typing.Any],
    source: typing.Literal['project', 'project_type', 'merged'],
) -> models.PluginAssignmentResponse:
    """Build a PluginAssignmentResponse from parsed plugin/edge dicts."""
    raw_identity = edge.get('identity_plugin_id')
    identity_plugin_id = (
        str(raw_identity)
        if isinstance(raw_identity, str) and raw_identity
        else None
    )
    return models.PluginAssignmentResponse(
        plugin_id=plugin['id'],
        plugin_slug=plugin['plugin_slug'],
        label=plugin['label'],
        tab=edge.get('tab', 'configuration'),
        default=bool(edge.get('default', False)),
        options=parse_options(edge.get('options')),
        source=source,
        identity_plugin_id=identity_plugin_id,
    )
