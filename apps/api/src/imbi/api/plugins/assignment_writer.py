"""Transactional ``USES {capability}`` replace for projects/project types.

Replaces every ``USES`` edge for a single capability kind on a parent
node (a Project or a ProjectType) in one server-side transaction, so a
mid-write failure cannot leave a partially-dropped assignment set. Edges
for other capability kinds on the same parent are untouched.
"""

from __future__ import annotations

import json
import typing

from imbi.api.graph_sql import escape_prop
from imbi.common import graph

_ROW_KEYS: tuple[str, ...] = (
    'integration_id',
    'default',
    'options',
    'env_payloads',
    'identity_integration_id',
)


class CapabilityAssignmentRow(typing.TypedDict):
    integration_id: str
    default: bool
    options: dict[str, typing.Any]
    env_payloads: typing.NotRequired[dict[str, dict[str, typing.Any]]]
    identity_integration_id: typing.NotRequired[str | None]


def _row_value(row: CapabilityAssignmentRow, key: str) -> typing.Any:
    if key == 'options':
        return json.dumps(row.get('options') or {})
    if key == 'env_payloads':
        value = row.get('env_payloads')
        return json.dumps(value) if value else None
    if key == 'identity_integration_id':
        return row.get('identity_integration_id') or None
    return row[key]  # type: ignore[literal-required]


def _rows_template(
    rows: list[CapabilityAssignmentRow],
) -> tuple[str, dict[str, typing.Any]]:
    if not rows:
        return '[]', {}
    maps: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, row in enumerate(rows):
        pairs: list[str] = []
        for key in _ROW_KEYS:
            placeholder = f'asgn_{i}_{key}'
            pairs.append(f'{escape_prop(key)}: {{{placeholder}}}')
            params[placeholder] = _row_value(row, key)
        maps.append('{{' + ', '.join(pairs) + '}}')
    return '[' + ', '.join(maps) + ']', params


async def replace_capability_assignments(
    db: graph.Graph,
    *,
    parent_label: typing.Literal['Project', 'ProjectType'],
    parent_key: typing.Literal['id', 'slug'],
    parent_value: str,
    org_slug: str,
    kind: str,
    rows: list[CapabilityAssignmentRow],
) -> None:
    """Atomically replace every ``USES {capability: kind}`` edge on a parent.

    The MATCH is scoped to ``org_slug`` through the parent's
    ``BELONGS_TO`` chain so a caller from another org cannot mutate edges
    by guessing the parent key. Callers validate integration ids and the
    one-default invariant up front; an empty ``rows`` clears the
    assignments for ``kind``.
    """
    parent_head = (
        f'MATCH (parent:{parent_label} {{{{{parent_key}: {{parent_value}}}}}})'
    )
    if parent_label == 'Project':
        parent_match = (
            parent_head + ' -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->'
            ' (:Organization {{slug: {org_slug}}})'
        )
    else:
        parent_match = (
            parent_head
            + ' -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
        )

    rows_tpl, row_params = _rows_template(rows)
    if rows:
        query = (
            parent_match + ' OPTIONAL MATCH (parent)-[old:USES]->()'
            ' WHERE old.capability = {kind}'
            ' DELETE old'
            ' WITH parent, count(old) AS _del'
            f' UNWIND {rows_tpl} AS row'
            ' MATCH (i:Integration {{id: row.integration_id}})'
            ' CREATE (parent)-[:USES {{capability: {kind},'
            ' default: row.default, options: row.options,'
            ' env_payloads: row.env_payloads,'
            ' identity_integration_id: row.identity_integration_id}}]->(i)'
        )
    else:
        query = (
            parent_match + ' OPTIONAL MATCH (parent)-[old:USES]->()'
            ' WHERE old.capability = {kind}'
            ' DELETE old'
        )

    await db.execute(
        query,
        {
            'parent_value': parent_value,
            'org_slug': org_slug,
            'kind': kind,
            **row_params,
        },
        [],
    )
