"""Generic CRUD for plugin-declared graph entities.

Validation, JSON schema, and Cypher are all derived from a plugin's
``PluginVertexLabel.model_ref`` at request time.
"""

import functools
import importlib
import json
import logging
import re
import types
import typing

import fastapi
import nanoid
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.graph_sql import props_template, set_clause
from imbi.common import graph
from imbi.common.plugins.errors import PluginNotFoundError
from imbi.common.plugins.registry import get_plugin

LOGGER = logging.getLogger(__name__)

# Cypher label identifiers are interpolated into queries as f-strings,
# so each label must be a simple identifier. A malformed plugin
# manifest must not be able to break out of the label position into
# arbitrary Cypher. Validated at the call site as defense-in-depth;
# the manifest loader should reject these earlier.
_CYPHER_IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')

plugin_entities_router = fastapi.APIRouter(
    prefix='/admin/plugins/{slug}/entities',
    tags=['Admin: Plugin Entities'],
)


def _import_model(model_ref: str) -> type[pydantic.BaseModel]:
    if ':' not in model_ref:
        raise fastapi.HTTPException(
            status_code=500,
            detail=(
                f'Invalid model_ref {model_ref!r} — expected '
                f"'module:ClassName'"
            ),
        )
    module_name, class_name = model_ref.split(':', 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise fastapi.HTTPException(
            status_code=500,
            detail=f'Could not import module {module_name!r}: {exc}',
        ) from exc
    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise fastapi.HTTPException(
            status_code=500,
            detail=f'Module {module_name!r} has no attribute {class_name!r}',
        ) from exc
    if not isinstance(cls, type) or not issubclass(cls, pydantic.BaseModel):
        raise fastapi.HTTPException(
            status_code=500,
            detail=(
                f'{model_ref!r} does not refer to a pydantic.BaseModel '
                f'subclass'
            ),
        )
    return cls


def _resolve_label(
    slug: str, label: str
) -> tuple[type[pydantic.BaseModel], str]:
    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {slug!r} is not installed',
        ) from exc
    for vlabel in entry.manifest.vertex_labels:
        if vlabel.name == label:
            if not _CYPHER_IDENTIFIER.match(vlabel.name):
                LOGGER.error(
                    'Plugin %r declares invalid vertex label %r',
                    slug,
                    vlabel.name,
                )
                raise fastapi.HTTPException(
                    status_code=500,
                    detail=(
                        f'Plugin {slug!r} declares invalid vertex label '
                        f'{vlabel.name!r}'
                    ),
                )
            return _import_model(vlabel.model_ref), vlabel.name
    raise fastapi.HTTPException(
        status_code=404,
        detail=f'Plugin {slug!r} does not declare entity label {label!r}',
    )


def _is_complex_type(annotation: typing.Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (dict, list):
        return True
    if origin is types.UnionType:
        return any(
            _is_complex_type(arg) for arg in typing.get_args(annotation)
        )
    return False


def _coerce_complex(
    model_cls: type[pydantic.BaseModel], props: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    # AGE round-trips dict/list properties as JSON-encoded strings; inflate
    # them before model_validate so pydantic sees the native shape.
    out: dict[str, typing.Any] = dict(props)
    for name, field in model_cls.model_fields.items():
        value = out.get(name)
        if not isinstance(value, str):
            continue
        if not _is_complex_type(field.annotation):
            continue
        try:
            out[name] = json.loads(value)
        except json.JSONDecodeError:
            LOGGER.warning(
                'Failed to JSON-decode %r field %r for %s',
                value,
                name,
                model_cls.__name__,
            )
    return out


def _row_to_model(
    model_cls: type[pydantic.BaseModel], raw: typing.Any
) -> dict[str, typing.Any]:
    parsed: typing.Any = graph.parse_agtype(raw)
    if not isinstance(parsed, dict):
        raise fastapi.HTTPException(
            status_code=500,
            detail='Unexpected vertex shape from graph',
        )
    props: dict[str, typing.Any] = {
        str(k): v  # pyright: ignore[reportUnknownArgumentType]
        for k, v in parsed.items()  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
    }
    instance = model_cls.model_validate(_coerce_complex(model_cls, props))
    return instance.model_dump(mode='json')


@functools.cache
def _create_model_for(
    base: type[pydantic.BaseModel],
) -> type[pydantic.BaseModel]:
    fields: dict[str, typing.Any] = {
        name: (field.annotation, field)
        for name, field in base.model_fields.items()
        if name != 'id'
    }
    return pydantic.create_model(  # type: ignore[call-overload]
        f'{base.__name__}Create',
        __base__=pydantic.BaseModel,
        **fields,
    )


@functools.cache
def _update_model_for(
    base: type[pydantic.BaseModel],
) -> type[pydantic.BaseModel]:
    fields: dict[str, typing.Any] = {}
    for name, field in base.model_fields.items():
        if name == 'id':
            continue
        ann: typing.Any = field.annotation
        new_ann: typing.Any = ann | None if ann is not None else None
        fields[name] = (new_ann, pydantic.Field(default=None))
    return pydantic.create_model(  # type: ignore[call-overload]
        f'{base.__name__}Update',
        __base__=pydantic.BaseModel,
        **fields,
    )


async def _fetch_one(
    db: graph.Graph,
    model_cls: type[pydantic.BaseModel],
    vlabel: str,
    id: str,
) -> dict[str, typing.Any]:
    query = f'MATCH (n:{vlabel} {{{{id: {{id}}}}}}) RETURN n LIMIT 1'
    rows = await db.execute(query, {'id': id}, ['n'])
    if not rows:
        raise fastapi.HTTPException(
            status_code=404, detail=f'{vlabel} {id!r} not found'
        )
    return _row_to_model(model_cls, rows[0]['n'])


@plugin_entities_router.get('/{label}/_schema')
async def get_entity_schema(
    slug: str,
    label: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Return the JSON schema for a plugin entity model."""
    _ = auth
    model_cls, _name = _resolve_label(slug, label)
    return model_cls.model_json_schema()


@plugin_entities_router.get('/{label}')
async def list_entities(
    slug: str,
    label: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List every node of the plugin's declared label."""
    _ = auth
    model_cls, vlabel = _resolve_label(slug, label)
    query = f'MATCH (n:{vlabel}) RETURN n ORDER BY coalesce(n.name, n.id)'
    rows = await db.execute(query, {}, ['n'])
    return [_row_to_model(model_cls, row['n']) for row in rows]


@plugin_entities_router.post('/{label}', status_code=201)
async def create_entity(
    slug: str,
    label: str,
    body: dict[str, typing.Any],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a new node of the plugin's declared label."""
    _ = auth
    model_cls, vlabel = _resolve_label(slug, label)
    try:
        validated = _create_model_for(model_cls).model_validate(body)
    except pydantic.ValidationError as exc:
        raise fastapi.HTTPException(
            status_code=400, detail=exc.errors()
        ) from exc
    payload = validated.model_dump(mode='json')
    payload['id'] = nanoid.generate()
    query = f'CREATE (n:{vlabel} {props_template(payload)}) RETURN n'
    with conflict_on_unique_violation(
        f'{vlabel} unique-index violation',
    ):
        rows = await db.execute(query, payload, ['n'])
    if not rows:
        raise fastapi.HTTPException(
            status_code=500, detail=f'{vlabel} create returned no rows'
        )
    return _row_to_model(model_cls, rows[0]['n'])


@plugin_entities_router.get('/{label}/{id}')
async def get_entity(
    slug: str,
    label: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Read a single node by its id."""
    _ = auth
    model_cls, vlabel = _resolve_label(slug, label)
    return await _fetch_one(db, model_cls, vlabel, id)


@plugin_entities_router.patch('/{label}/{id}')
async def update_entity(
    slug: str,
    label: str,
    id: str,
    body: dict[str, typing.Any],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partial update by id.

    Unset fields are left alone; sending ``null`` clears optional fields.
    Sending ``id`` is rejected (the URL param is canonical).
    """
    _ = auth
    body.pop('id', None)
    model_cls, vlabel = _resolve_label(slug, label)
    try:
        validated = _update_model_for(model_cls).model_validate(body)
    except pydantic.ValidationError as exc:
        raise fastapi.HTTPException(
            status_code=400, detail=exc.errors()
        ) from exc
    fields = validated.model_dump(mode='json', exclude_unset=True)
    if not fields:
        return await _fetch_one(db, model_cls, vlabel, id)
    set_stmt = set_clause('n', fields)
    query = f'MATCH (n:{vlabel} {{{{id: {{id}}}}}}) {set_stmt} RETURN n'
    rows = await db.execute(query, {**fields, 'id': id}, ['n'])
    if not rows:
        raise fastapi.HTTPException(
            status_code=404, detail=f'{vlabel} {id!r} not found'
        )
    return _row_to_model(model_cls, rows[0]['n'])


@plugin_entities_router.delete('/{label}/{id}', status_code=204)
async def delete_entity(
    slug: str,
    label: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:plugins:manage'),
        ),
    ],
) -> fastapi.Response:
    """Hard-delete the node and any edges touching it."""
    _ = auth
    _model_cls, vlabel = _resolve_label(slug, label)
    query = f'MATCH (n:{vlabel} {{{{id: {{id}}}}}}) DETACH DELETE n'
    await db.execute(query, {'id': id}, [])
    return fastapi.Response(status_code=204)


__all__ = ['plugin_entities_router']
