"""Plugin assignment endpoints for projects."""

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

project_plugins_router = fastapi.APIRouter(tags=['Project Plugins'])


@project_plugins_router.get('/')
async def get_project_plugins(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[models.PluginAssignmentResponse]:
    """Merged view: project-type defaults + project overrides."""
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->
          (o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (proj)-[:TYPE]->(pt:ProjectType)
                   -[pte:USES_PLUGIN]->(p2:Plugin)
    WITH proj, collect({{plugin: p2{{.*}}, edge: pte{{.*}},
                         src: 'project_type'}}) AS pt_rows
    OPTIONAL MATCH (proj)-[pe:USES_PLUGIN]->(p:Plugin)
    WITH pt_rows, collect({{plugin: p{{.*}}, edge: pe{{.*}},
                            src: 'project'}}) AS proj_rows
    RETURN pt_rows, proj_rows
    """
    records = await db.execute(
        query,
        {'project_id': project_id, 'org_slug': org_slug},
        ['pt_rows', 'proj_rows'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Project not found',
        )

    pt_rows: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['pt_rows']) or []
    )
    proj_rows: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['proj_rows']) or []
    )

    merged: dict[str, dict[str, typing.Any]] = {}
    for row in pt_rows:
        plugin = graph.parse_agtype(row.get('plugin'))
        if plugin and plugin.get('id'):
            merged[plugin['id']] = {
                'plugin': plugin,
                'edge': graph.parse_agtype(row.get('edge')) or {},
                'source': 'project_type',
            }
    for row in proj_rows:
        plugin = graph.parse_agtype(row.get('plugin'))
        if plugin and plugin.get('id'):
            merged[plugin['id']] = {
                'plugin': plugin,
                'edge': graph.parse_agtype(row.get('edge')) or {},
                'source': 'project',
            }

    return [
        build_assignment_response(v['plugin'], v['edge'], v['source'])
        for v in merged.values()
        if v['plugin'].get('id')
    ]


@project_plugins_router.put('/')
async def replace_project_plugins(
    org_slug: str,
    project_id: str,
    assignments: list[models.PluginAssignmentCreate],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> list[models.PluginAssignmentResponse]:
    """Replace project-level plugin overrides."""
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

    if rows:
        try:
            validate_one_default_per_tab(rows)
        except ValueError as exc:
            raise fastapi.HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

    # Pre-validate every submitted plugin_id before any destructive
    # delete runs. Otherwise an unknown id silently no-ops and the
    # endpoint reports success with a partially dropped assignment set.
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

    # Scope mutations to the org via the project's team→org chain so a
    # caller from another org can't modify edges by guessing project_id.
    delete_query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->
          (:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (proj)-[e:USES_PLUGIN]->()
    DELETE e
    RETURN count(e) AS deleted
    """
    await db.execute(
        delete_query,
        {'project_id': project_id, 'org_slug': org_slug},
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
        create_query: str = (
            'MATCH (proj:Project {{id: {project_id}}})'
            ' -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->'
            ' (:Organization {{slug: {org_slug}}})'
            ' MATCH (p:Plugin {{id: {plugin_id}}})'
            f' CREATE (proj)-[:USES_PLUGIN {props_template(edge_props)}]->(p)'
        )
        await db.execute(
            create_query,
            {
                'project_id': project_id,
                'org_slug': org_slug,
                'plugin_id': row['plugin_id'],
                **edge_props,
            },
        )

    return await get_project_plugins(org_slug, project_id, db, auth)
