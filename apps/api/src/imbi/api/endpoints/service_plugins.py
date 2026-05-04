"""Plugin CRUD endpoints for third-party services."""

import json
import typing

import fastapi
import nanoid
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
