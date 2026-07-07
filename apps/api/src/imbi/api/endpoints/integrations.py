"""Integration (configured plugin instance) management endpoints."""

import json
import typing

import fastapi
from imbi_common import graph
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.auth import login_providers, permissions
from imbi_api.domain import models
from imbi_api.endpoints._helpers import conflict_on_unique_violation
from imbi_api.graph_sql import escape_prop, props_template, set_clause
from imbi_api.plugins import parse_options
from imbi_api.plugins.assignments import hydrate_integration
from imbi_api.plugins.credentials import patch_integration_credentials

integrations_router = fastapi.APIRouter(tags=['Integrations'])


def _build_response(
    props: dict[str, typing.Any],
) -> models.IntegrationResponse:
    """Build an ``IntegrationResponse`` from a hydrated Integration node."""
    integration = hydrate_integration(props)
    encrypted_credentials: dict[str, typing.Any] = (
        integration.get('encrypted_credentials') or {}
    )
    credential_fields = sorted(encrypted_credentials)
    raw_capabilities: dict[str, typing.Any] = (
        integration.get('capabilities') or {}
    )
    capabilities = {
        kind: models.CapabilityToggle(
            **typing.cast('dict[str, typing.Any]', state)
        )
        for kind, state in raw_capabilities.items()
        if isinstance(state, dict)
    }
    return models.IntegrationResponse(
        plugin=integration['plugin'],
        name=integration['name'],
        slug=integration['slug'],
        description=integration.get('description'),
        icon=integration.get('icon'),
        vendor=integration.get('vendor'),
        service_url=integration.get('service_url'),
        category=integration.get('category'),
        status=integration.get('status', 'active'),
        options=integration.get('options') or {},
        capabilities=capabilities,
        credential_fields=credential_fields,
        links=integration.get('links') or {},
        identifiers=integration.get('identifiers') or {},
        organization=integration.get('organization'),
        team=integration.get('team'),
    )


_LIST_QUERY: typing.LiteralString = """
MATCH (i:Integration)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (i)-[:MANAGED_BY]->(t:Team)
RETURN i{{.*, organization: o{{.*}}, team: t{{.*}}}} AS integration
ORDER BY i.name
"""

_GET_QUERY: typing.LiteralString = """
MATCH (i:Integration {{slug: {slug}}})
      -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (i)-[:MANAGED_BY]->(t:Team)
RETURN i{{.*, organization: o{{.*}}, team: t{{.*}}}} AS integration
"""


@integrations_router.get('/')
async def list_integrations(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:read'),
        ),
    ],
) -> list[models.IntegrationResponse]:
    """List integrations configured in an organization."""
    _ = auth
    records = await db.execute(
        _LIST_QUERY, {'org_slug': org_slug}, ['integration']
    )
    return [
        _build_response(graph.parse_agtype(r['integration'])) for r in records
    ]


@integrations_router.post('/', status_code=201)
async def create_integration(
    org_slug: str,
    data: models.IntegrationCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:create'),
        ),
    ],
) -> models.IntegrationResponse:
    """Create a new Integration -- a configured instance of a plugin.

    Raises:
        400: The referenced plugin is not installed.
        404: Organization or team not found.
        409: An integration with this slug already exists.

    """
    _ = auth
    try:
        entry = get_plugin(data.plugin)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Plugin {data.plugin!r} is not installed',
        ) from exc

    capabilities: dict[str, typing.Any] = {}
    for capability in entry.manifest.capabilities:
        toggle = data.capabilities.get(capability.kind)
        if toggle is not None:
            capabilities[capability.kind] = {
                'enabled': toggle.enabled,
                'options': toggle.options,
            }
        else:
            capabilities[capability.kind] = {
                'enabled': capability.default_enabled,
                'options': {},
            }

    encryptor = TokenEncryption.get_instance()
    encrypted_credentials = {
        field: encryptor.encrypt(value)
        for field, value in data.credentials.items()
    }

    props: dict[str, typing.Any] = {
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': data.icon,
        'plugin': data.plugin,
        'vendor': data.vendor,
        'service_url': (str(data.service_url) if data.service_url else None),
        'category': data.category,
        'status': data.status,
        'options': data.options,
        'encrypted_credentials': encrypted_credentials,
        'capabilities': capabilities,
        'links': data.links,
        'identifiers': data.identifiers,
    }

    create_tpl = props_template(props)

    if data.team_slug is not None:
        query: str = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            ' MATCH (t:Team {{slug: {team_slug}}})'
            ' -[:BELONGS_TO]->(o)'
            f' CREATE (i:Integration {create_tpl})'
            ' CREATE (i)-[:BELONGS_TO]->(o)'
            ' CREATE (i)-[:MANAGED_BY]->(t)'
            ' RETURN i{{.*, organization: o{{.*}},'
            ' team: t{{.*}}}} AS integration'
        )
        params: dict[str, typing.Any] = {
            'org_slug': org_slug,
            'team_slug': data.team_slug,
            **props,
        }
    else:
        query = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            f' CREATE (i:Integration {create_tpl})'
            ' CREATE (i)-[:BELONGS_TO]->(o)'
            ' RETURN i{{.*, organization: o{{.*}},'
            ' team: null}} AS integration'
        )
        params = {'org_slug': org_slug, **props}

    with conflict_on_unique_violation(
        f'Integration with slug {data.slug!r} already exists',
    ):
        records = await db.execute(query, params, ['integration'])

    if not records:
        if data.team_slug:
            raise fastapi.HTTPException(
                status_code=404,
                detail=(
                    f'Organization {org_slug!r} '
                    f'or team {data.team_slug!r} not found'
                ),
            )
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )

    return _build_response(graph.parse_agtype(records[0]['integration']))


@integrations_router.get('/{slug}')
async def get_integration(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:read'),
        ),
    ],
) -> models.IntegrationResponse:
    """Get an Integration by slug.

    Raises:
        404: Integration not found.

    """
    _ = auth
    records = await db.execute(
        _GET_QUERY, {'slug': slug, 'org_slug': org_slug}, ['integration']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )
    return _build_response(graph.parse_agtype(records[0]['integration']))


def _merged_update_props(
    data: models.IntegrationUpdate,
    existing: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Build the SET-able props for an ``IntegrationUpdate``.

    Only fields present in ``model_fields_set`` are included.
    ``options`` and ``capabilities`` are merged into the existing values
    rather than replacing them wholesale.
    """
    sent = data.model_fields_set
    props: dict[str, typing.Any] = {}
    simple_fields = (
        'name',
        'description',
        'icon',
        'vendor',
        'category',
        'status',
        'links',
        'identifiers',
    )
    for field in simple_fields:
        if field in sent:
            props[field] = getattr(data, field)
    if 'service_url' in sent:
        props['service_url'] = (
            str(data.service_url) if data.service_url else None
        )
    if 'options' in sent:
        props['options'] = {
            **(existing.get('options') or {}),
            **(data.options or {}),
        }
    if 'capabilities' in sent:
        merged_caps: dict[str, typing.Any] = dict(
            existing.get('capabilities') or {}
        )
        for kind, toggle in (data.capabilities or {}).items():
            current: dict[str, typing.Any] = merged_caps.get(kind) or {}
            merged_caps[kind] = {
                'enabled': toggle.enabled,
                'options': {
                    **(current.get('options') or {}),
                    **toggle.options,
                },
            }
        props['capabilities'] = merged_caps
    return props


@integrations_router.patch('/{slug}')
async def update_integration(
    org_slug: str,
    slug: str,
    data: models.IntegrationUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:update'),
        ),
    ],
) -> models.IntegrationResponse:
    """Partially update an Integration.

    Only fields present in the request body are applied. ``capabilities``
    and ``options`` are merged into the existing values rather than
    replaced wholesale.

    Raises:
        404: Integration not found.
        409: Slug conflict (name/team rename collisions are not possible
            here since slug is immutable via this endpoint).

    """
    _ = auth
    records = await db.execute(
        _GET_QUERY, {'slug': slug, 'org_slug': org_slug}, ['integration']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )
    existing = hydrate_integration(
        graph.parse_agtype(records[0]['integration'])
    )

    sent = data.model_fields_set
    props = _merged_update_props(data, existing)

    if 'team_slug' in sent:
        if data.team_slug:
            query: str = (
                'MATCH (i:Integration {{slug: {slug}}})'
                ' -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
                ' MATCH (t:Team {{slug: {team_slug}}})'
                '-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
                ' OPTIONAL MATCH (i)-[old_mgr:MANAGED_BY]->()'
                ' DELETE old_mgr'
                ' WITH i, t'
                + (f' {set_clause("i", props)}' if props else '')
                + ' CREATE (i)-[:MANAGED_BY]->(t)'
                ' WITH i'
                ' MATCH (i)-[:BELONGS_TO]->(o:Organization)'
                ' RETURN i{{.*, organization: o{{.*}},'
                ' team: t{{.*}}}} AS integration'
            )
            params: dict[str, typing.Any] = {
                'slug': slug,
                'org_slug': org_slug,
                'team_slug': data.team_slug,
                **props,
            }
        else:
            query = (
                'MATCH (i:Integration {{slug: {slug}}})'
                ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
                ' OPTIONAL MATCH (i)-[old_mgr:MANAGED_BY]->()'
                ' DELETE old_mgr'
                ' WITH i, o'
                + (f' {set_clause("i", props)}' if props else '')
                + ' RETURN i{{.*, organization: o{{.*}},'
                ' team: null}} AS integration'
            )
            params = {'slug': slug, 'org_slug': org_slug, **props}
    else:
        if not props:
            return _build_response(
                graph.parse_agtype(records[0]['integration'])
            )
        set_stmt = set_clause('i', props)
        query = (
            'MATCH (i:Integration {{slug: {slug}}})'
            ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
            ' OPTIONAL MATCH (i)-[:MANAGED_BY]->(t:Team)'
            f' {set_stmt}'
            ' RETURN i{{.*, organization: o{{.*}},'
            ' team: t{{.*}}}} AS integration'
        )
        params = {'slug': slug, 'org_slug': org_slug, **props}

    with conflict_on_unique_violation(
        f'Integration with slug {slug!r} already exists',
    ):
        updated = await db.execute(query, params, ['integration'])

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )

    return _build_response(graph.parse_agtype(updated[0]['integration']))


@integrations_router.delete('/{slug}', status_code=204)
async def delete_integration(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:delete'),
        ),
    ],
) -> None:
    """Delete an Integration.

    Raises:
        404: Integration not found.

    """
    _ = auth
    query: typing.LiteralString = """
    MATCH (i:Integration {{slug: {slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE i
    RETURN count(i) AS deleted
    """
    records = await db.execute(
        query, {'slug': slug, 'org_slug': org_slug}, ['deleted']
    )
    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )


@integrations_router.put('/{slug}/credentials')
async def update_integration_credentials(
    org_slug: str,
    slug: str,
    data: models.IntegrationCredentialsUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:update'),
        ),
    ],
) -> dict[str, list[str]]:
    """Patch an Integration's encrypted credentials.

    Raises:
        404: Integration not found.
        409: Concurrent modification; retry.

    """
    _ = auth
    fields = await patch_integration_credentials(
        db, slug, org_slug, data.credentials
    )
    return {'credential_fields': fields}


@integrations_router.put('/{slug}/login-provider')
async def set_login_provider(
    org_slug: str,
    slug: str,
    data: models.LoginProviderUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:update'),
        ),
    ],
) -> models.IntegrationResponse:
    """Promote or demote an Integration as the org's SSO login provider.

    Setting ``used_as_login=true`` requires the Integration's plugin to
    declare an ``identity`` capability carrying the ``login_capable``
    hint, and demotes any other login provider in the organization so at
    most one is flagged per org. The login-provider cache is invalidated
    on any change.

    Raises:
        400: The plugin does not declare a login-capable identity
            capability.
        404: Integration not found.

    """
    _ = auth
    records = await db.execute(
        _GET_QUERY, {'slug': slug, 'org_slug': org_slug}, ['integration']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )
    integration = hydrate_integration(
        graph.parse_agtype(records[0]['integration'])
    )

    if data.used_as_login:
        _require_login_capable(str(integration.get('plugin') or ''))
        # At most one login provider per org: clear the flag on siblings.
        await db.execute(
            """
            MATCH (other:Integration)-[:BELONGS_TO]->
                  (:Organization {{slug: {org_slug}}})
            WHERE other.slug <> {slug} AND other.used_as_login = true
            SET other.used_as_login = false
            """,
            {'org_slug': org_slug, 'slug': slug},
            [],
        )

    updated = await db.execute(
        """
        MATCH (i:Integration {{slug: {slug}}})
              -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
        OPTIONAL MATCH (i)-[:MANAGED_BY]->(t:Team)
        SET i.used_as_login = {used_as_login}
        RETURN i{{.*, organization: o{{.*}}, team: t{{.*}}}} AS integration
        """,
        {
            'slug': slug,
            'org_slug': org_slug,
            'used_as_login': data.used_as_login,
        },
        ['integration'],
    )
    login_providers.invalidate_cache()
    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )
    return _build_response(graph.parse_agtype(updated[0]['integration']))


def _require_login_capable(plugin_slug: str) -> None:
    """Raise 400 unless ``plugin_slug`` declares a login-capable identity.

    Raises:
        fastapi.HTTPException: 400 when the plugin is not installed or
            its ``identity`` capability lacks the ``login_capable`` hint.

    """
    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Plugin {plugin_slug!r} is not installed',
        ) from exc
    capability = entry.manifest.get_capability('identity')
    if capability is None or not capability.hints.get('login_capable'):
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin {plugin_slug!r} does not declare a login-capable '
                f'identity capability'
            ),
        )


_TYPE_ASSIGNMENTS_QUERY: typing.LiteralString = """
MATCH (pt:ProjectType)-[e:USES]->
      (i:Integration {{slug: {slug}}})-[:BELONGS_TO]->
      (:Organization {{slug: {org_slug}}})
WHERE e.capability = {kind}
RETURN pt.slug AS project_type_slug, e{{.*}} AS edge
ORDER BY pt.slug
"""


async def _resolve_identity_integration_id(
    db: graph.Graph,
    org_slug: str,
    identity_integration_slug: str | None,
) -> str | None:
    """Resolve an identity Integration slug to its id within ``org_slug``.

    Raises:
        fastapi.HTTPException: 404 if the slug does not resolve.

    """
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


@integrations_router.get('/{slug}/capabilities/{kind}/assignments')
async def list_capability_assignments(
    org_slug: str,
    slug: str,
    kind: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:read'),
        ),
    ],
) -> list[models.CapabilityAssignment]:
    """List an Integration capability's project-type assignments."""
    _ = auth
    records = await db.execute(
        _TYPE_ASSIGNMENTS_QUERY,
        {'slug': slug, 'org_slug': org_slug, 'kind': kind},
        ['project_type_slug', 'edge'],
    )
    assignments: list[models.CapabilityAssignment] = []
    for record in records:
        edge: dict[str, typing.Any] = graph.parse_agtype(record['edge']) or {}
        identity_id: typing.Any = edge.get('identity_integration_id')
        identity_slug: str | None = None
        if identity_id:
            identity_slug = await _identity_slug_by_id(
                db, org_slug, str(identity_id)
            )
        assignments.append(
            models.CapabilityAssignment(
                project_type_slug=graph.parse_agtype(
                    record['project_type_slug']
                ),
                default=bool(edge.get('default')),
                options=parse_options(edge.get('options')),
                env_payloads=parse_options(edge.get('env_payloads')),
                identity_integration_slug=identity_slug,
            )
        )
    return assignments


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


class _TypeAssignmentRow(typing.TypedDict):
    project_type_slug: str
    default: bool
    options: dict[str, typing.Any]
    env_payloads: dict[str, dict[str, typing.Any]]
    identity_integration_id: str | None


_TYPE_ASSIGNMENT_ROW_KEYS: tuple[str, ...] = (
    'project_type_slug',
    'default',
    'options',
    'env_payloads',
    'identity_integration_id',
)


def _type_assignment_row_value(row: _TypeAssignmentRow, key: str) -> object:
    if key == 'options':
        return json.dumps(row['options'] or {})
    if key == 'env_payloads':
        return json.dumps(row['env_payloads']) if row['env_payloads'] else None
    return row[key]  # type: ignore[literal-required]


@integrations_router.put('/{slug}/capabilities/{kind}/assignments')
async def replace_capability_assignments_endpoint(
    org_slug: str,
    slug: str,
    kind: str,
    data: models.CapabilityAssignmentsUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('integration:update'),
        ),
    ],
) -> list[models.CapabilityAssignment]:
    """Replace a capability's project-type assignments for one Integration.

    Only ``USES`` edges of ``kind`` from *this* Integration are replaced;
    other integrations' assignments for the same capability are untouched
    (unlike :func:`imbi_api.plugins.assignment_writer.replace_capability_
    assignments`, which is scoped per-parent and would wipe every
    integration bound to that project type).

    Raises:
        404: Integration, a referenced project type, or a referenced
            identity integration was not found.

    """
    _ = auth
    integration_records = await db.execute(
        _GET_QUERY, {'slug': slug, 'org_slug': org_slug}, ['integration']
    )
    if not integration_records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration with slug {slug!r} not found',
        )

    if data.assignments:
        type_slugs = sorted({a.project_type_slug for a in data.assignments})
        check_query: typing.LiteralString = """
        UNWIND {slugs} AS s
        OPTIONAL MATCH (pt:ProjectType {{slug: s}})
              -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
        RETURN count(DISTINCT pt) AS found
        """
        found_records = await db.execute(
            check_query,
            {'slugs': type_slugs, 'org_slug': org_slug},
            ['found'],
        )
        found = (
            graph.parse_agtype(found_records[0]['found'])
            if found_records
            else 0
        )
        if found != len(type_slugs):
            raise fastapi.HTTPException(
                status_code=404,
                detail='One or more project type slugs are invalid',
            )

    rows: list[_TypeAssignmentRow] = []
    for assignment in data.assignments:
        identity_integration_id = await _resolve_identity_integration_id(
            db, org_slug, assignment.identity_integration_slug
        )
        rows.append(
            {
                'project_type_slug': assignment.project_type_slug,
                'default': assignment.default,
                'options': assignment.options,
                'env_payloads': assignment.env_payloads,
                'identity_integration_id': identity_integration_id,
            }
        )

    await _replace_type_assignments_for_integration(
        db,
        org_slug=org_slug,
        integration_slug=slug,
        kind=kind,
        rows=rows,
    )

    return await list_capability_assignments(org_slug, slug, kind, db, auth)


async def _replace_type_assignments_for_integration(
    db: graph.Graph,
    *,
    org_slug: str,
    integration_slug: str,
    kind: str,
    rows: list[_TypeAssignmentRow],
) -> None:
    """Atomically replace ``(:ProjectType)-[USES {{capability}}]->(this)``.

    Scoped to a single Integration (``integration_slug``) so other
    integrations' assignments of the same capability on the same project
    types are untouched -- unlike
    :func:`imbi_api.plugins.assignment_writer.replace_capability_assignments`,
    which replaces every ``USES`` edge of ``kind`` on the *parent*
    (all integrations bound to that project type).
    """
    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'slug': integration_slug,
        'kind': kind,
    }
    maps: list[str] = []
    for i, row in enumerate(rows):
        pairs: list[str] = []
        for key in _TYPE_ASSIGNMENT_ROW_KEYS:
            placeholder = f'asgn_{i}_{key}'
            pairs.append(f'{escape_prop(key)}: {{{placeholder}}}')
            params[placeholder] = _type_assignment_row_value(row, key)
        maps.append('{{' + ', '.join(pairs) + '}}')
    rows_tpl = '[' + ', '.join(maps) + ']' if maps else '[]'

    delete_clause: typing.LiteralString = (
        'MATCH (i:Integration {{slug: {slug}}})'
        ' -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
        ' OPTIONAL MATCH (:ProjectType)-[old:USES]->(i)'
        ' WHERE old.capability = {kind}'
        ' DELETE old'
    )

    if rows:
        query = (
            delete_clause
            + ' WITH i, count(old) AS _del'
            + f' UNWIND {rows_tpl} AS row'
            + ' MATCH (pt:ProjectType {{slug: row.project_type_slug}})'
            ' -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
            ' CREATE (pt)-[:USES {{capability: {kind},'
            ' default: row.default, options: row.options,'
            ' env_payloads: row.env_payloads,'
            ' identity_integration_id: row.identity_integration_id}}]->(i)'
        )
    else:
        query = delete_clause

    await db.execute(query, params, [])
