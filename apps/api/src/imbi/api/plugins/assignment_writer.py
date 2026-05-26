"""Transactional ``USES_PLUGIN`` replace for projects and project types.

The pre-existing ``replace_project_plugins`` /
``replace_project_type_plugins`` performed a two-step
"DELETE all, then CREATE one-by-one" sequence with N+1 separate
``db.execute`` calls.  If any CREATE failed midway, the project or
project type was left with a partially dropped assignment set (the
DELETE landed, only some CREATEs ran) — see punchlist **H11**.

This module fuses the DELETE + UNWIND CREATE into a single Cypher
statement so AGE wraps the whole replace in one server-side
transaction.  A failure during validation aborts before the DELETE
runs; a failure during the fused write rolls back the DELETE too.
"""

from __future__ import annotations

import json
import typing

from imbi_common import graph

from imbi_api.graph_sql import escape_prop
from imbi_api.plugins.assignments import PluginAssignmentRow

_ROW_KEYS: tuple[str, ...] = (
    'plugin_id',
    'tab',
    'default',
    'options',
    'identity_plugin_id',
    'env_payloads',
)


def _assignment_rows_template(
    rows: list[PluginAssignmentRow],
) -> tuple[str, dict[str, typing.Any]]:
    """Build an inline Cypher list of maps + the params dict.

    Mirrors the ``_env_entries_template`` pattern in ``projects.py``:
    each row's values become indexed placeholders so the resulting
    query is safe to pass through ``sql.SQL.format``. Optional fields
    (``identity_plugin_id``, ``env_payloads``) are always emitted --
    null when absent -- so every row in the UNWIND has the same shape;
    downstream readers already treat missing and null the same.
    """
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


def _row_value(row: PluginAssignmentRow, key: str) -> typing.Any:
    """Pull a row field; JSON-encode dict-valued ones for AGE storage."""
    if key == 'options':
        return json.dumps(row['options'])
    if key == 'env_payloads':
        value = row.get('env_payloads')
        return json.dumps(value) if value else None
    if key == 'identity_plugin_id':
        return row.get('identity_plugin_id') or None
    return row[key]  # type: ignore[literal-required]


async def replace_assignments(
    db: graph.Graph,
    *,
    parent_label: typing.Literal['Project', 'ProjectType'],
    parent_key: typing.Literal['id', 'slug'],
    parent_value: str,
    org_slug: str,
    rows: list[PluginAssignmentRow],
) -> None:
    """Atomically replace every ``USES_PLUGIN`` edge on a parent node.

    The MATCH clause scopes the write to ``org_slug`` via the parent's
    ``BELONGS_TO`` chain so a caller from another org cannot mutate
    edges by guessing the parent key.

    Callers must validate plugin ids, identity_plugin_ids, and the
    one-default-per-tab invariant up front; passing an empty ``rows``
    list clears all assignments.
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

    rows_tpl, row_params = _assignment_rows_template(rows)
    if rows:
        # ``count(old)`` collapses the post-DELETE rows back to one row
        # per parent. Without it, ``OPTIONAL MATCH`` emits one row per
        # pre-existing edge, and the following ``UNWIND`` would then run
        # once per old edge -- creating ``K x N`` edges when the parent
        # already had ``K`` assignments.
        query = (
            parent_match + ' OPTIONAL MATCH (parent)-[old:USES_PLUGIN]->()'
            ' DELETE old'
            ' WITH parent, count(old) AS _del'
            f' UNWIND {rows_tpl} AS row'
            ' MATCH (p:Plugin {{id: row.plugin_id}})'
            ' CREATE (parent)-[:USES_PLUGIN {{tab: row.tab,'
            ' default: row.default,'
            ' options: row.options,'
            ' identity_plugin_id: row.identity_plugin_id,'
            ' env_payloads: row.env_payloads}}]->(p)'
        )
    else:
        query = (
            parent_match + ' OPTIONAL MATCH (parent)-[old:USES_PLUGIN]->()'
            ' DELETE old'
        )

    await db.execute(
        query,
        {
            'parent_value': parent_value,
            'org_slug': org_slug,
            **row_params,
        },
        [],
    )
