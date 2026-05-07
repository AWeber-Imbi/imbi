"""Plugin assignment endpoints for project types."""

import json
import typing

import fastapi
from imbi_common import graph

from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.graph_sql import props_template
from imbi_api.plugins.assignments import (
    PluginAssignmentRow,
    build_assignment_response,
    validate_identity_plugin_ids,
    validate_one_default_per_tab,
)

project_type_plugins_router = fastapi.APIRouter(
    tags=['Project Type Plugins'],
)


def _from_record(
    record: dict[str, typing.Any],
    source: typing.Literal['project', 'project_type', 'merged'],
) -> models.PluginAssignmentResponse:
    plugin = graph.parse_agtype(record['plugin'])
    edge = graph.parse_agtype(record.get('edge', '{}')) or {}  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    return build_assignment_response(plugin, edge, source)  # pyright: ignore[reportUnknownArgumentType]


@project_type_plugins_router.get('/')
async def list_project_type_plugins(
    org_slug: str,
    pt_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:read'),
        ),
    ],
) -> list[models.PluginAssignmentResponse]:
    """List default plugin assignments for a project type."""
    query: typing.LiteralString = """
    MATCH (pt:ProjectType {{slug: {pt_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (pt)-[e:USES_PLUGIN]->(p:Plugin)
    RETURN p{{.*}} AS plugin, e{{.*}} AS edge
    ORDER BY p.label
    """
    records = await db.execute(
        query,
        {'pt_slug': pt_slug, 'org_slug': org_slug},
        ['plugin', 'edge'],
    )
    return [_from_record(r, 'project_type') for r in records]


@project_type_plugins_router.put('/')
async def replace_project_type_plugins(
    org_slug: str,
    pt_slug: str,
    assignments: list[models.PluginAssignmentCreate],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:update'),
        ),
    ],
) -> list[models.PluginAssignmentResponse]:
    """Replace all plugin assignments for a project type."""
    rows: list[PluginAssignmentRow] = [
        PluginAssignmentRow(
            plugin_id=a.plugin_id,
            tab=a.tab,
            default=a.default,
            options=a.options,
            identity_plugin_id=a.identity_plugin_id,
        )
        for a in assignments
    ]
    try:
        validate_one_default_per_tab(rows)
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # Validate every submitted plugin_id before destructive deletes.
    # Otherwise an unknown id is silently dropped on re-create and the
    # endpoint can return success with a partially cleared assignment
    # set (the existing edges have been deleted, but the new edges to
    # invalid plugin ids are never created).
    if rows:
        plugin_ids = sorted({row['plugin_id'] for row in rows})
        validate_query: typing.LiteralString = """
        UNWIND {plugin_ids} AS pid
        OPTIONAL MATCH (p:Plugin {{id: pid}})
        RETURN count(DISTINCT p) AS found
        """
        found_records = await db.execute(
            validate_query,
            {'plugin_ids': plugin_ids},
            ['found'],
        )
        found = (
            graph.parse_agtype(found_records[0]['found'])
            if found_records
            else 0
        )
        if found != len(plugin_ids):
            raise fastapi.HTTPException(
                status_code=404,
                detail='One or more plugin IDs are invalid',
            )

        await validate_identity_plugin_ids(
            db,
            org_slug,
            sorted(
                {iid for row in rows if (iid := row.get('identity_plugin_id'))}
            ),
        )

    delete_query: typing.LiteralString = """
    MATCH (pt:ProjectType {{slug: {pt_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (pt)-[e:USES_PLUGIN]->()
    DELETE e
    RETURN count(e) AS deleted
    """
    await db.execute(
        delete_query,
        {'pt_slug': pt_slug, 'org_slug': org_slug},
        ['deleted'],
    )

    for row in rows:
        edge_props: dict[str, typing.Any] = {
            'tab': row['tab'],
            'default': row['default'],
            'options': json.dumps(row['options']),
        }
        identity_id = row.get('identity_plugin_id')
        if identity_id:
            edge_props['identity_plugin_id'] = identity_id
        merge_query: str = (
            'MATCH (pt:ProjectType {{slug: {pt_slug}}})'
            ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
            ' MATCH (p:Plugin {{id: {plugin_id}}})'
            f' CREATE (pt)-[:USES_PLUGIN {props_template(edge_props)}]->(p)'
        )
        await db.execute(
            merge_query,
            {
                'pt_slug': pt_slug,
                'org_slug': org_slug,
                'plugin_id': row['plugin_id'],
                **edge_props,
            },
        )

    return await list_project_type_plugins(org_slug, pt_slug, db, auth)
