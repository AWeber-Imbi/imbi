"""Project-level Integration capability assignment endpoints."""

import collections
import typing

import fastapi

from imbi.api.auth import permissions
from imbi.api.domain import models
from imbi.api.plugins import parse_options
from imbi.api.plugins.assignment_writer import (
    CapabilityAssignmentRow,
    replace_capability_assignments,
)
from imbi.api.plugins.assignments import (
    capability_enabled,
    hydrate_integration,
)
from imbi.common import graph

project_integrations_router = fastapi.APIRouter(
    prefix='/organizations/{org_slug}/projects/{project_id}/integrations',
    tags=['Project Integrations'],
)


_LIST_QUERY: typing.LiteralString = """
MATCH (proj:Project {{id: {project_id}}})
      -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->
      (:Organization {{slug: {org_slug}}})
MATCH (proj)-[e:USES]->(i:Integration)
RETURN i.slug AS integration_slug, e{{.*}} AS edge
ORDER BY i.slug
"""


async def _identity_slug_by_id(
    db: graph.Graph, org_slug: str, integration_id: str
) -> str | None:
    query: typing.LiteralString = """
    MATCH (i:Integration {{id: {id}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN i.slug AS slug
    """
    records = await db.execute(
        query, {'id': integration_id, 'org_slug': org_slug}, ['slug']
    )
    if not records:
        return None
    return str(graph.parse_agtype(records[0]['slug']))


@project_integrations_router.get('/')
async def list_project_integrations(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[models.ProjectIntegrationAssignment]:
    """List a project's ``USES`` capability overrides."""
    _ = auth
    records = await db.execute(
        _LIST_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['integration_slug', 'edge'],
    )
    assignments: list[models.ProjectIntegrationAssignment] = []
    for record in records:
        edge: dict[str, typing.Any] = graph.parse_agtype(record['edge']) or {}
        identity_id: typing.Any = edge.get('identity_integration_id')
        identity_slug: str | None = None
        if identity_id:
            identity_slug = await _identity_slug_by_id(
                db, org_slug, str(identity_id)
            )
        assignments.append(
            models.ProjectIntegrationAssignment(
                integration_slug=graph.parse_agtype(
                    record['integration_slug']
                ),
                capability=edge.get('capability', ''),
                default=bool(edge.get('default')),
                options=parse_options(edge.get('options')),
                env_payloads=parse_options(edge.get('env_payloads')),
                identity_integration_slug=identity_slug,
            )
        )
    return assignments


async def _project_org_slug(
    db: graph.Graph, project_id: str, org_slug: str
) -> str:
    """Confirm ``project_id`` exists in ``org_slug`` and return it.

    Raises:
        fastapi.HTTPException: 404 if the project is not in this org.

    """
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->
          (o:Organization {{slug: {org_slug}}})
    RETURN o.slug AS org_slug
    """
    records = await db.execute(
        query, {'project_id': project_id, 'org_slug': org_slug}, ['org_slug']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found in organization'
            f' {org_slug!r}',
        )
    return str(graph.parse_agtype(records[0]['org_slug']))


async def _org_integrations_by_slug(
    db: graph.Graph, org_slug: str, slugs: list[str]
) -> dict[str, dict[str, typing.Any]]:
    """Return hydrated Integration props for ``slugs`` in ``org_slug``."""
    if not slugs:
        return {}
    query: typing.LiteralString = """
    UNWIND {slugs} AS s
    MATCH (i:Integration {{slug: s}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN i
    """
    records = await db.execute(
        query, {'slugs': slugs, 'org_slug': org_slug}, ['i']
    )
    out: dict[str, dict[str, typing.Any]] = {}
    for record in records:
        props: typing.Any = graph.parse_agtype(record['i'])
        if not isinstance(props, dict):
            continue
        typed_props = typing.cast('dict[str, typing.Any]', props)
        if typed_props.get('slug'):
            out[str(typed_props['slug'])] = hydrate_integration(typed_props)
    return out


async def _resolve_identity_integration_id(
    db: graph.Graph,
    org_slug: str,
    identity_integration_slug: str | None,
) -> str | None:
    if identity_integration_slug is None:
        return None
    query: typing.LiteralString = """
    MATCH (i:Integration {{slug: {slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN i.id AS id
    """
    records = await db.execute(
        query,
        {'slug': identity_integration_slug, 'org_slug': org_slug},
        ['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                'Identity integration with slug '
                f'{identity_integration_slug!r} not found'
            ),
        )
    return str(graph.parse_agtype(records[0]['id']))


@project_integrations_router.put('/')
async def replace_project_integrations(
    org_slug: str,
    project_id: str,
    data: models.ProjectIntegrationsUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> list[models.ProjectIntegrationAssignment]:
    """Replace a project's ``USES`` capability overrides.

    Every submitted integration slug must belong to the project's
    organization and have the targeted capability enabled. Rows are
    grouped by capability kind and each kind's assignments are replaced
    atomically via
    :func:`imbi.api.plugins.assignment_writer.replace_capability_assignments`.

    Raises:
        404: Project not found, or an integration/identity-integration
            slug does not resolve within the organization.
        400: A referenced integration does not have the targeted
            capability enabled.

    """
    _ = auth
    await _project_org_slug(db, project_id, org_slug)

    existing_records = await db.execute(
        _LIST_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['integration_slug', 'edge'],
    )
    existing_kinds: set[str] = set()
    for r in existing_records:
        existing_edge: dict[str, typing.Any] = (
            graph.parse_agtype(r['edge']) or {}
        )
        if existing_edge.get('capability'):
            existing_kinds.add(existing_edge['capability'])

    slugs = sorted({a.integration_slug for a in data.assignments})
    integrations = await _org_integrations_by_slug(db, org_slug, slugs)
    missing = [s for s in slugs if s not in integrations]
    if missing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Unknown integration slug(s): {missing}',
        )

    for assignment in data.assignments:
        integration = integrations[assignment.integration_slug]
        if not capability_enabled(integration, assignment.capability):
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Integration {assignment.integration_slug!r} does not'
                    f' have capability {assignment.capability!r} enabled'
                ),
            )

    rows_by_kind: dict[str, list[CapabilityAssignmentRow]] = (
        collections.defaultdict(list)
    )
    for assignment in data.assignments:
        integration = integrations[assignment.integration_slug]
        identity_integration_id = await _resolve_identity_integration_id(
            db, org_slug, assignment.identity_integration_slug
        )
        row: CapabilityAssignmentRow = {
            'integration_id': str(integration['id']),
            'default': assignment.default,
            'options': assignment.options,
        }
        if assignment.env_payloads:
            row['env_payloads'] = assignment.env_payloads
        if identity_integration_id is not None:
            row['identity_integration_id'] = identity_integration_id
        rows_by_kind[assignment.capability].append(row)

    for kind in set(rows_by_kind) | existing_kinds:
        await replace_capability_assignments(
            db,
            parent_label='Project',
            parent_key='id',
            parent_value=project_id,
            org_slug=org_slug,
            kind=kind,
            rows=rows_by_kind.get(kind, []),
        )

    return await list_project_integrations(org_slug, project_id, db, auth)
