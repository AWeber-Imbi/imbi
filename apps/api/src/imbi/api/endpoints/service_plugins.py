"""Plugin CRUD endpoints for third-party services."""

import json
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph
from imbi_common.plugins.errors import (
    PluginNotFoundError,
)
from imbi_common.plugins.registry import (
    get_plugin,
    list_plugins,
)

from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.graph_sql import props_template, set_clause
from imbi_api.plugins import parse_options as _parse_options
from imbi_api.plugins.credentials import (
    get_plugin_configuration_keys,
    patch_plugin_configuration,
)

service_plugins_router = fastapi.APIRouter(tags=['Service Plugins'])


def _registry_slugs() -> set[str]:
    return {e.manifest.slug for e in list_plugins()}


def _build_plugin_response(
    record: dict[str, typing.Any],
    registry_slugs: set[str],
) -> models.PluginResponse:
    plugin = graph.parse_agtype(record['plugin'])
    svc = graph.parse_agtype(record.get('svc')) if record.get('svc') else {}  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    slug = plugin['plugin_slug']
    return models.PluginResponse(
        id=plugin['id'],
        plugin_slug=slug,
        label=plugin['label'],
        options=_parse_options(plugin.get('options')),
        api_version=plugin.get('api_version', 1),
        status='active' if slug in registry_slugs else 'unavailable',
        service_slug=svc.get('slug') if svc else None,  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
    )


@service_plugins_router.get('/')
async def list_service_plugins(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:read'),
        ),
    ],
) -> list[models.PluginResponse]:
    """List Plugin nodes linked to a third-party service."""
    query: typing.LiteralString = """
    MATCH (p:Plugin)<-[:HAS_PLUGIN]-(s:ThirdPartyService {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN p{{.*}} AS plugin, s{{.*}} AS svc
    ORDER BY p.label
    """
    records = await db.execute(
        query,
        {'svc_slug': slug, 'org_slug': org_slug},
        ['plugin', 'svc'],
    )
    registry = _registry_slugs()
    return [_build_plugin_response(r, registry) for r in records]


@service_plugins_router.post('/', status_code=201)
async def create_service_plugin(
    org_slug: str,
    slug: str,
    data: models.PluginCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:update'),
        ),
    ],
) -> models.PluginResponse:
    """Create a Plugin node linked to a third-party service."""
    try:
        entry = get_plugin(data.plugin_slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Plugin {data.plugin_slug!r} is not installed',
        ) from exc

    check_query: typing.LiteralString = """
    MATCH (p:Plugin {{label: {label}}})<-[:HAS_PLUGIN]-
          (s:ThirdPartyService {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN count(p) AS cnt
    """
    check = await db.execute(
        check_query,
        {'label': data.label, 'svc_slug': slug, 'org_slug': org_slug},
        ['cnt'],
    )
    if check and graph.parse_agtype(check[0]['cnt']) > 0:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Plugin with label {data.label!r} already exists'
                f' in service {slug!r}'
            ),
        )

    plugin_id = nanoid.generate()
    options_str = json.dumps(data.options)
    props: dict[str, typing.Any] = {
        'id': plugin_id,
        'plugin_slug': data.plugin_slug,
        'label': data.label,
        'options': options_str,
        'api_version': entry.manifest.api_version,
    }
    tpl = props_template(props)

    create_query: str = (
        'MATCH (s:ThirdPartyService {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' CREATE (p:Plugin {tpl})'
        ' CREATE (s)-[:HAS_PLUGIN]->(p)'
        ' RETURN p{{.*}} AS plugin, s{{.*}} AS svc'
    )
    records = await db.execute(
        create_query,
        {'svc_slug': slug, 'org_slug': org_slug, **props},
        ['plugin', 'svc'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Third-party service {slug!r} not found',
        )
    return _build_plugin_response(records[0], _registry_slugs())


@service_plugins_router.put('/{plugin_id}')
async def update_service_plugin(
    org_slug: str,
    slug: str,
    plugin_id: str,
    data: models.PluginUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:update'),
        ),
    ],
) -> models.PluginResponse:
    """Update a Plugin node's label and options."""
    # Mirror the duplicate-label check from ``create_service_plugin`` so
    # rename via PUT can't bypass uniqueness within the service.
    dup_check_query: typing.LiteralString = """
    MATCH (p:Plugin)<-[:HAS_PLUGIN]-
          (s:ThirdPartyService {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WHERE p.label = {label} AND p.id <> {plugin_id}
    RETURN count(p) AS cnt
    """
    dup_check = await db.execute(
        dup_check_query,
        {
            'svc_slug': slug,
            'org_slug': org_slug,
            'label': data.label,
            'plugin_id': plugin_id,
        },
        ['cnt'],
    )
    if dup_check and graph.parse_agtype(dup_check[0]['cnt']) > 0:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Plugin with label {data.label!r} already exists'
                f' in service {slug!r}'
            ),
        )

    options_str = json.dumps(data.options)
    props: dict[str, typing.Any] = {
        'label': data.label,
        'options': options_str,
    }
    set_stmt = set_clause('p', props)

    update_query: str = (
        'MATCH (p:Plugin {{id: {plugin_id}}})'
        '<-[:HAS_PLUGIN]-(s:ThirdPartyService {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' {set_stmt}'
        ' RETURN p{{.*}} AS plugin, s{{.*}} AS svc'
    )
    records = await db.execute(
        update_query,
        {
            'plugin_id': plugin_id,
            'svc_slug': slug,
            'org_slug': org_slug,
            **props,
        },
        ['plugin', 'svc'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_id!r} not found in service {slug!r}',
        )
    return _build_plugin_response(records[0], _registry_slugs())


@service_plugins_router.delete('/{plugin_id}', status_code=204)
async def delete_service_plugin(
    org_slug: str,
    slug: str,
    plugin_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:update'),
        ),
    ],
    force: bool = fastapi.Query(default=False),
) -> None:
    """Delete a Plugin node.

    Rejects if any USES_PLUGIN edges still reference it unless
    ``?force=true`` is passed by an admin.
    """
    # ``force=true`` bypasses the in-use-by-projects safeguard, so it
    # must require admin privileges to match the docstring contract.
    if force and not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='force delete requires admin privileges',
        )

    if not force:
        ref_query: typing.LiteralString = """
        MATCH ()-[r:USES_PLUGIN]->(p:Plugin {{id: {plugin_id}}})
        RETURN count(r) AS cnt
        """
        ref_records = await db.execute(
            ref_query,
            {'plugin_id': plugin_id},
            ['cnt'],
        )
        refs = graph.parse_agtype(ref_records[0]['cnt']) if ref_records else 0
        if refs and refs > 0:
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    f'Plugin {plugin_id!r} is still assigned to'
                    f' {refs} project(s) or project-type(s);'
                    f' use ?force=true to override'
                ),
            )

    delete_query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    <-[:HAS_PLUGIN]-(s:ThirdPartyService {{slug: {svc_slug}}})
    -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DETACH DELETE p
    RETURN count(p) AS deleted
    """
    records = await db.execute(
        delete_query,
        {
            'plugin_id': plugin_id,
            'svc_slug': slug,
            'org_slug': org_slug,
        },
        ['deleted'],
    )
    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_id!r} not found in service {slug!r}',
        )


async def _ensure_plugin_in_service(
    db: graph.Graph, org_slug: str, svc_slug: str, plugin_id: str
) -> str:
    """Validate the plugin belongs to the named service and return slug."""
    query: typing.LiteralString = """
    MATCH (p:Plugin {{id: {plugin_id}}})
    <-[:HAS_PLUGIN]-(s:ThirdPartyService {{slug: {svc_slug}}})
    -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN p.plugin_slug AS slug
    LIMIT 1
    """
    records = await db.execute(
        query,
        {
            'plugin_id': plugin_id,
            'svc_slug': svc_slug,
            'org_slug': org_slug,
        },
        ['slug'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_id!r} not found in service {svc_slug!r}',
        )
    slug: str = graph.parse_agtype(records[0]['slug'])
    return slug


@service_plugins_router.get('/{plugin_id}/configuration')
async def get_service_plugin_configuration(
    org_slug: str,
    slug: str,
    plugin_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Return populated credential field names for a Plugin instance.

    Plaintext values are never returned. The UI uses ``populated``
    only to decide which inputs to render as "set / re-enter" vs
    "empty".
    """
    plugin_slug = await _ensure_plugin_in_service(
        db, org_slug, slug, plugin_id
    )
    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_slug!r} is not loaded',
        ) from exc
    if entry.manifest.auth_type != 'api_token':
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Plugin {plugin_slug!r} uses auth_type='
                f'{entry.manifest.auth_type!r}; configuration is managed'
                ' through the third-party service application'
            ),
        )
    populated = await get_plugin_configuration_keys(db, plugin_id)
    return {
        'plugin_slug': plugin_slug,
        'auth_type': entry.manifest.auth_type,
        'fields': [c.model_dump() for c in entry.manifest.credentials],
        'populated': populated,
    }


@service_plugins_router.patch('/{plugin_id}/configuration')
async def patch_service_plugin_configuration(
    org_slug: str,
    slug: str,
    plugin_id: str,
    body: dict[str, str | None],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partial-update a Plugin instance's encrypted configuration.

    ``body`` is a flat ``{field_name: value}`` mapping. ``null`` or
    empty values clear the field. Field names are validated against
    the manifest's ``credentials[]``; unknown fields are rejected.
    """
    plugin_slug = await _ensure_plugin_in_service(
        db, org_slug, slug, plugin_id
    )
    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_slug!r} is not loaded',
        ) from exc
    if entry.manifest.auth_type != 'api_token':
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Plugin {plugin_slug!r} uses auth_type='
                f'{entry.manifest.auth_type!r}; configure via OAuth2'
            ),
        )
    allowed = {c.name for c in entry.manifest.credentials}
    unknown = set(body) - allowed
    if unknown:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Unknown credential fields {sorted(unknown)};'
                f' allowed: {sorted(allowed)}'
            ),
        )
    populated = await patch_plugin_configuration(db, plugin_id, body)
    return {
        'plugin_slug': plugin_slug,
        'auth_type': entry.manifest.auth_type,
        'fields': [c.model_dump() for c in entry.manifest.credentials],
        'populated': populated,
    }


class _AssignmentInput(pydantic.BaseModel):
    project_type_slug: str
    tab: typing.Literal['configuration', 'logs']
    default: bool = False
    options: dict[str, typing.Any] = {}


class _AssignmentRow(pydantic.BaseModel):
    project_type_slug: str
    project_type_name: str
    tab: typing.Literal['configuration', 'logs']
    default: bool
    options: dict[str, typing.Any]


async def _list_assignments(
    db: graph.Graph, org_slug: str, plugin_id: str
) -> list[_AssignmentRow]:
    query: typing.LiteralString = """
    MATCH (pt:ProjectType)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (pt)-[e:USES_PLUGIN]->(p:Plugin {{id: {plugin_id}}})
    RETURN pt{{.*}} AS pt, e{{.*}} AS edge
    ORDER BY pt.name
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug, 'plugin_id': plugin_id},
        ['pt', 'edge'],
    )
    rows: list[_AssignmentRow] = []
    for r in records:
        pt: dict[str, typing.Any] = (  # pyright: ignore[reportUnknownVariableType]
            graph.parse_agtype(r['pt']) or {}
        )
        edge: dict[str, typing.Any] = (  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            graph.parse_agtype(r.get('edge', '{}')) or {}
        )
        rows.append(
            _AssignmentRow(
                project_type_slug=pt.get('slug', ''),
                project_type_name=pt.get('name', ''),
                tab=edge.get('tab', 'configuration'),
                default=bool(edge.get('default', False)),
                options=_parse_options(edge.get('options')),
            )
        )
    return rows


@service_plugins_router.get('/{plugin_id}/assignments')
async def list_plugin_assignments(
    org_slug: str,
    slug: str,
    plugin_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:read'),
        ),
    ],
) -> list[_AssignmentRow]:
    """List project types this plugin instance is assigned to."""
    await _ensure_plugin_in_service(db, org_slug, slug, plugin_id)
    return await _list_assignments(db, org_slug, plugin_id)


@service_plugins_router.put('/{plugin_id}/assignments')
async def replace_plugin_assignments(
    org_slug: str,
    slug: str,
    plugin_id: str,
    body: list[_AssignmentInput],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:update'),
        ),
    ],
) -> list[_AssignmentRow]:
    """Replace this plugin instance's project-type bindings.

    Drops every ``USES_PLUGIN`` edge from any ProjectType in
    ``org_slug`` that points at this Plugin, then recreates edges
    from ``body``. Project-level overrides are left alone.
    """
    plugin_slug = await _ensure_plugin_in_service(
        db, org_slug, slug, plugin_id
    )
    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_slug!r} is not loaded',
        ) from exc

    allowed_tab = entry.manifest.plugin_type
    bad_tab = [a for a in body if a.tab != allowed_tab]
    if bad_tab:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Plugin type {allowed_tab!r} can only be assigned to'
                f' the {allowed_tab!r} tab'
            ),
        )

    seen: set[tuple[str, str]] = set()
    for a in body:
        key = (a.project_type_slug, a.tab)
        if key in seen:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Duplicate assignment for project type'
                    f' {a.project_type_slug!r} on tab {a.tab!r}'
                ),
            )
        seen.add(key)

    if body:
        pt_slugs = sorted({a.project_type_slug for a in body})
        check_query: typing.LiteralString = """
        UNWIND {slugs} AS s
        OPTIONAL MATCH (pt:ProjectType {{slug: s}})
                -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
        RETURN count(DISTINCT pt) AS found
        """
        found_records = await db.execute(
            check_query,
            {'slugs': pt_slugs, 'org_slug': org_slug},
            ['found'],
        )
        found = (
            graph.parse_agtype(found_records[0]['found'])
            if found_records
            else 0
        )
        if found != len(pt_slugs):
            raise fastapi.HTTPException(
                status_code=404,
                detail='One or more project_type_slug values are invalid',
            )

    delete_query: typing.LiteralString = """
    MATCH (pt:ProjectType)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (pt)-[e:USES_PLUGIN]->(p:Plugin {{id: {plugin_id}}})
    DELETE e
    """
    await db.execute(
        delete_query,
        {'org_slug': org_slug, 'plugin_id': plugin_id},
        [],
    )

    clear_default_query: typing.LiteralString = """
    MATCH (pt:ProjectType {{slug: {pt_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (pt)-[e:USES_PLUGIN]->(:Plugin)
    WHERE e.tab = {tab} AND e.default = true
    SET e.default = false
    """

    for a in body:
        edge_props = {
            'tab': a.tab,
            'default': a.default,
            'options': json.dumps(a.options),
        }
        if a.default:
            await db.execute(
                clear_default_query,
                {
                    'pt_slug': a.project_type_slug,
                    'org_slug': org_slug,
                    'tab': a.tab,
                },
                [],
            )
        create_query: str = (
            'MATCH (pt:ProjectType {{slug: {pt_slug}}})'
            ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
            ' MATCH (p:Plugin {{id: {plugin_id}}})'
            f' CREATE (pt)-[:USES_PLUGIN {props_template(edge_props)}]->(p)'
        )
        await db.execute(
            create_query,
            {
                'pt_slug': a.project_type_slug,
                'org_slug': org_slug,
                'plugin_id': plugin_id,
                **edge_props,
            },
        )

    return await _list_assignments(db, org_slug, plugin_id)
