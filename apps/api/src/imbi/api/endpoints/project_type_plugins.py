"""Plugin assignment endpoints for project types."""

import typing

import fastapi
from imbi_common import graph

from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.plugins.assignment_writer import replace_assignments
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
            env_payloads=a.env_payloads,
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

    # ``replace_assignments`` fuses delete + creates into a single
    # Cypher statement so a mid-replace failure rolls back atomically.
    await replace_assignments(
        db,
        parent_label='ProjectType',
        parent_key='slug',
        parent_value=pt_slug,
        org_slug=org_slug,
        rows=rows,
    )

    return await list_project_type_plugins(org_slug, pt_slug, db, auth)
