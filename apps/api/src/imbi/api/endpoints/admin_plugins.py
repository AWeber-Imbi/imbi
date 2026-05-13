"""Admin plugin management endpoints."""

import importlib.metadata
import json
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph
from imbi_common.plugins.errors import (
    PluginNotFoundError,
)
from imbi_common.plugins.registry import (
    RegistryEntry,
    get_plugin,
    list_plugins,
)

from imbi_api.auth import permissions
from imbi_api.endpoints import plugin_edges as _plugin_edges
from imbi_api.plugins.lifecycle import (
    get_enabled_map,
    set_plugin_enabled,
)

LOGGER = logging.getLogger(__name__)

admin_plugins_router = fastapi.APIRouter(
    prefix='/admin', tags=['Admin: Plugins']
)


_VERTEX_OVERRIDE_FIELDS: tuple[str, ...] = (
    'display_name',
    'description',
    'nav_label',
)


class _PluginOverrides(typing.TypedDict, total=False):
    widget_text: str | None
    vertex_label_overrides: dict[str, dict[str, str | None]]


def _decode_property(raw: typing.Any) -> typing.Any:
    """Parse an agtype-encoded property, JSON-decoding string maps."""
    if raw is None:
        return None
    parsed: typing.Any = graph.parse_agtype(raw)
    if isinstance(parsed, str):
        try:
            return json.loads(parsed)
        except json.JSONDecodeError:
            return parsed
    return parsed


async def _read_overrides(db: graph.Graph, slug: str) -> _PluginOverrides:
    return (await _read_all_overrides(db)).get(slug, {})


def _row_to_overrides(row: dict[str, typing.Any]) -> _PluginOverrides:
    out: _PluginOverrides = {}
    widget = _decode_property(row.get('widget_text'))
    if widget is not None:
        out['widget_text'] = widget if isinstance(widget, str) else None
    vlabels = _decode_property(row.get('vertex_overrides'))
    if isinstance(vlabels, dict):
        cleaned: dict[str, dict[str, str | None]] = {}
        for label, fields in vlabels.items():  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
            if not isinstance(fields, dict):
                continue
            entry: dict[str, str | None] = {}
            for key, value in fields.items():  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
                if key in _VERTEX_OVERRIDE_FIELDS and (
                    value is None or isinstance(value, str)
                ):
                    entry[str(key)] = value  # pyright: ignore[reportUnknownArgumentType]
            if entry:
                cleaned[str(label)] = entry  # pyright: ignore[reportUnknownArgumentType]
        if cleaned:
            out['vertex_label_overrides'] = cleaned
    return out


async def _read_all_overrides(
    db: graph.Graph,
) -> dict[str, _PluginOverrides]:
    """Return ``{slug: overrides}`` for every registered plugin."""
    query: typing.LiteralString = (
        'MATCH (r:PluginRegistration) '
        'RETURN r.slug AS slug, '
        'r.widget_text_override AS widget_text, '
        'r.vertex_label_overrides AS vertex_overrides'
    )
    rows = await db.execute(
        query, {}, ['slug', 'widget_text', 'vertex_overrides']
    )
    out: dict[str, _PluginOverrides] = {}
    for row in rows:
        slug_raw = row.get('slug')
        if slug_raw is None:
            continue
        slug = graph.parse_agtype(slug_raw)
        if not isinstance(slug, str):
            continue
        out[slug] = _row_to_overrides(row)
    return out


def _resolve_widget_text(
    manifest_value: str | None, override: str | None
) -> str | None:
    if override is not None and override != '':
        return override
    return manifest_value


def _serialize_vertex_label(
    vlabel: typing.Any,
    overrides: dict[str, str | None] | None,
) -> dict[str, typing.Any]:
    """Return a vertex_label dict including resolved + raw override values."""
    raw = vlabel.model_dump()
    resolved: dict[str, typing.Any] = {**raw, 'overrides': overrides or {}}
    for field in _VERTEX_OVERRIDE_FIELDS:
        manifest_value = raw.get(field)
        override_value = (overrides or {}).get(field)
        if override_value is not None and override_value != '':
            resolved[field] = override_value
        else:
            resolved[field] = manifest_value
    return resolved


def _serialize(
    entry: RegistryEntry,
    enabled: bool,
    service_icon: str | None = None,
    overrides: _PluginOverrides | None = None,
) -> dict[str, typing.Any]:
    overrides = overrides or {}
    widget_default = getattr(entry.manifest, 'widget_text', None)
    widget_override = overrides.get('widget_text')
    vertex_overrides = overrides.get('vertex_label_overrides') or {}
    return {
        'slug': entry.manifest.slug,
        'name': entry.manifest.name,
        'description': entry.manifest.description,
        'api_version': entry.manifest.api_version,
        'auth_type': entry.manifest.auth_type,
        'cacheable': entry.manifest.cacheable,
        'enabled': enabled,
        'icon': service_icon,
        'login_capable': entry.manifest.login_capable,
        'package_name': entry.package_name,
        'package_version': entry.package_version,
        'plugin_type': entry.manifest.plugin_type,
        'requires_identity': entry.manifest.requires_identity,
        'docs_url': getattr(entry.manifest, 'docs_url', None),
        'supported_tabs': [entry.manifest.plugin_type],
        'supports_deployment_sync': bool(
            getattr(entry.manifest, 'supports_deployment_sync', False)
        ),
        'options': [o.model_dump() for o in entry.manifest.options],
        'credentials': [c.model_dump() for c in entry.manifest.credentials],
        'vertex_labels': [
            _serialize_vertex_label(v, vertex_overrides.get(v.name))
            for v in entry.manifest.vertex_labels
        ],
        'edge_labels': [e.model_dump() for e in entry.manifest.edge_labels],
        'widget_text': _resolve_widget_text(widget_default, widget_override),
        'widget_text_default': widget_default,
        'widget_text_override': widget_override,
        'ops_log_templates': {
            action: tpl.model_dump()
            for action, tpl in entry.manifest.ops_log_templates.items()
        },
    }


def _placeholder(package_name: str) -> dict[str, typing.Any]:
    return {
        'slug': package_name,
        'name': package_name,
        'description': '',
        'api_version': 0,
        'auth_type': 'api_token',
        'cacheable': False,
        'enabled': False,
        'icon': None,
        'login_capable': False,
        'package_name': package_name,
        'package_version': None,
        'plugin_type': None,
        'requires_identity': False,
        'docs_url': None,
        'supported_tabs': [],
        'supports_deployment_sync': False,
        'options': [],
        'credentials': [],
        'vertex_labels': [],
        'edge_labels': [],
        'widget_text': None,
        'widget_text_default': None,
        'widget_text_override': None,
        'ops_log_templates': {},
    }


async def _service_icon_by_slug(db: graph.Graph) -> dict[str, str]:
    """Return ``{plugin_slug: parent_service_icon}``.

    A plugin slug can be attached to multiple ``ThirdPartyService`` nodes
    (e.g. an org with two AWS environments).  The user-facing
    Connections UI just needs *some* representative brand glyph — the
    first non-null icon we see wins.  Plugins not attached to any
    service yield no entry; the UI renders a fallback.
    """
    query: typing.LiteralString = (
        'MATCH (s:ThirdPartyService)-[:HAS_PLUGIN]->(p:Plugin) '
        'WHERE s.icon IS NOT NULL '
        'RETURN p.plugin_slug AS slug, s.icon AS icon'
    )
    rows = await db.execute(query, {}, ['slug', 'icon'])
    out: dict[str, str] = {}
    for row in rows:
        slug_raw = row.get('slug')
        icon_raw = row.get('icon')
        if slug_raw is None or icon_raw is None:
            continue
        slug = graph.parse_agtype(slug_raw)
        icon = graph.parse_agtype(icon_raw)
        if slug and icon and slug not in out:
            out[slug] = icon
    return out


@admin_plugins_router.get('/plugins')
async def list_installed_plugins(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """List installed plugins with enabled state.

    The UI splits this list by ``enabled`` — disabled rows render as
    "Catalog" entries that admins can promote, enabled rows render as
    "Installed" entries available for assignment.
    """
    _ = auth
    enabled_map = await get_enabled_map(db)
    icons = await _service_icon_by_slug(db)
    overrides_map = await _read_all_overrides(db)
    registered = list_plugins()
    known_packages = {e.package_name for e in registered}

    installed: list[dict[str, typing.Any]] = [
        _serialize(
            entry,
            enabled_map.get(entry.manifest.slug, False),
            icons.get(entry.manifest.slug),
            overrides_map.get(entry.manifest.slug, {}),
        )
        for entry in registered
    ]

    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name', '') or ''
        if (
            name.lower().startswith('imbi-plugin-')
            and name not in known_packages
        ):
            installed.append(_placeholder(name))

    return {'installed': installed}


@admin_plugins_router.get('/plugins/{slug}')
async def get_installed_plugin(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Get details for a single installed plugin."""
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    enabled_map = await get_enabled_map(db)
    icons = await _service_icon_by_slug(db)
    overrides = await _read_overrides(db, slug)
    payload = _serialize(
        entry,
        enabled_map.get(entry.manifest.slug, False),
        icons.get(entry.manifest.slug),
        overrides,
    )
    payload['data_types'] = [d.model_dump() for d in entry.manifest.data_types]
    return payload


class _PluginPatchPayload(pydantic.BaseModel):
    """Partial-update payload for ``PATCH /admin/plugins/{slug}``.

    A field absent from the request leaves the stored value alone; a
    field sent as ``null`` clears the override (UI inherits the manifest
    default).  ``model_fields_set`` distinguishes the two.
    """

    enabled: bool | None = None
    widget_text: str | None = None
    vertex_label_overrides: dict[str, dict[str, str | None]] | None = None


async def _set_widget_text_override(
    db: graph.Graph, slug: str, value: str | None
) -> None:
    if value is None or value == '':
        query: typing.LiteralString = (
            'MERGE (r:PluginRegistration {{slug: {slug}}}) '
            'REMOVE r.widget_text_override'
        )
        await db.execute(query, {'slug': slug}, [])
        return
    query = (
        'MERGE (r:PluginRegistration {{slug: {slug}}}) '
        'SET r.widget_text_override = {value}'
    )
    await db.execute(query, {'slug': slug, 'value': value}, [])


async def _set_vertex_label_overrides(
    db: graph.Graph,
    slug: str,
    incoming: dict[str, dict[str, str | None]] | None,
) -> None:
    """Merge ``incoming`` into the stored override dict.

    A ``null`` value at the field level clears that field; an empty
    inner dict clears every override for that label.  Passing ``None``
    here clears every override entirely.
    """
    existing = (await _read_overrides(db, slug)).get(
        'vertex_label_overrides'
    ) or {}
    if incoming is None:
        merged: dict[str, dict[str, str | None]] = {}
    else:
        merged = {k: dict(v) for k, v in existing.items()}
        for label, fields in incoming.items():
            if not fields:
                merged.pop(label, None)
                continue
            current = dict(merged.get(label, {}))
            for field_name, value in fields.items():
                if field_name not in _VERTEX_OVERRIDE_FIELDS:
                    continue
                if value is None or value == '':
                    current.pop(field_name, None)
                else:
                    current[field_name] = value
            if current:
                merged[label] = current
            else:
                merged.pop(label, None)
    if merged:
        encoded = json.dumps(merged)
        query: typing.LiteralString = (
            'MERGE (r:PluginRegistration {{slug: {slug}}}) '
            'SET r.vertex_label_overrides = {value}'
        )
        await db.execute(query, {'slug': slug, 'value': encoded}, [])
    else:
        query = (
            'MERGE (r:PluginRegistration {{slug: {slug}}}) '
            'REMOVE r.vertex_label_overrides'
        )
        await db.execute(query, {'slug': slug}, [])


@admin_plugins_router.get('/plugins/{slug}/edges')
async def list_plugin_edges(
    slug: str,
    rel_type: str,
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, list[_plugin_edges.EdgeResponse]]:
    """Bulk-fetch every Environment-anchored edge of ``rel_type`` for an org.

    Returns ``{env_slug: [edges]}`` for every environment in ``org_slug``,
    including environments with no outgoing edge (empty list).  Used by
    the plugin admin UI to render the per-org edge mapping table without
    one HTTP request per environment.
    """
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    declares = any(
        edge.name == rel_type and 'Environment' in edge.from_labels
        for edge in entry.manifest.edge_labels
    )
    if not declares:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Plugin {slug!r} does not declare Environment edge '
                f'{rel_type!r}'
            ),
        )
    return await _plugin_edges.list_org_environment_edges(
        db=db, rel_type=rel_type, org_slug=org_slug
    )


@admin_plugins_router.patch('/plugins/{slug}')
async def update_installed_plugin(
    slug: str,
    body: _PluginPatchPayload,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Update a plugin's enabled flag and/or operator overrides.

    Field semantics for the override fields:

    * field absent — leave alone
    * field ``null`` — clear all overrides (revert to manifest)
    * field present — set/merge override values
    """
    _ = auth
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc

    sent = body.model_fields_set
    if body.enabled is not None:
        await set_plugin_enabled(db, slug, body.enabled)

    if 'widget_text' in sent:
        await _set_widget_text_override(db, slug, body.widget_text)

    if 'vertex_label_overrides' in sent:
        await _set_vertex_label_overrides(
            db, slug, body.vertex_label_overrides
        )

    enabled_map = await get_enabled_map(db)
    icons = await _service_icon_by_slug(db)
    overrides = await _read_overrides(db, slug)
    payload = _serialize(
        entry,
        enabled_map.get(entry.manifest.slug, False),
        icons.get(entry.manifest.slug),
        overrides,
    )
    payload['data_types'] = [d.model_dump() for d in entry.manifest.data_types]
    return payload
