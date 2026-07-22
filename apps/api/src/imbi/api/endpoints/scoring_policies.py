"""Scoring policy CRUD endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import typing

import fastapi
import pydantic

from imbi.api import patch as json_patch
from imbi.api.auth import permissions
from imbi.api.domain import scoring as scoring_models
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.scoring import OptionalValkeyClient
from imbi.api.scoring import queue as score_queue
from imbi.common import graph
from imbi.common.scoring import models as scoring_common

LOGGER = logging.getLogger(__name__)

scoring_policies_router = fastapi.APIRouter(
    prefix='/scoring/policies', tags=['Scoring']
)

PolicyType = (
    scoring_common.AttributePolicy
    | scoring_common.PresencePolicy
    | scoring_common.LinkPresencePolicy
    | scoring_common.AgePolicy
    | scoring_common.AnalysisResultPolicy
    | scoring_common.DeploymentStatusPolicy
    | scoring_common.ConditionPolicy
)


# AGE stores nested objects as strings; these keys round-trip through JSON.
_JSON_PROPS_KEYS = (
    'value_score_map',
    'range_score_map',
    'age_score_map',
    'status_score_map',
    'condition',
)


# Flat properties that live directly on the ScoringPolicy node. Nested
# maps are stored as JSON strings via _serialize_props.
_NODE_PROPERTY_KEYS: frozenset[str] = frozenset(
    {
        'id',
        'name',
        'slug',
        'description',
        'category',
        'weight',
        'enabled',
        'priority',
        'attribute_name',
        'link_slug',
        'result_slug',
        'environment_slug',
        'present_score',
        'missing_score',
        'value_score_map',
        'range_score_map',
        'age_score_map',
        'status_score_map',
        'condition',
        'true_score',
        'false_score',
    }
)


_POLICY_ADAPTER: pydantic.TypeAdapter[PolicyType] = pydantic.TypeAdapter(
    scoring_common.ScoringPolicy
)


def _parse_node(raw: dict[str, typing.Any]) -> dict[str, typing.Any]:
    out = dict(raw)
    for key in _JSON_PROPS_KEYS:
        val = out.get(key)
        if isinstance(val, str):
            try:
                out[key] = json.loads(val)
            except TypeError, ValueError:
                out[key] = None
    return out


def _validate_policy_row(
    raw: dict[str, typing.Any], targets: list[str]
) -> PolicyType | None:
    cleaned = _parse_node(raw)
    cleaned['targets'] = targets
    cleaned.setdefault('category', 'attribute')
    try:
        return _POLICY_ADAPTER.validate_python(cleaned)
    except pydantic.ValidationError:
        LOGGER.warning(
            'Skipping malformed scoring policy: %s', cleaned.get('slug')
        )
        return None


async def load_policy(db: graph.Graph, slug: str) -> PolicyType | None:
    query: typing.LiteralString = (
        'MATCH (sp:ScoringPolicy {{slug: {slug}}})'
        ' OPTIONAL MATCH (sp)-[:TARGETS]->(pt:ProjectType)'
        ' RETURN sp, collect(pt.slug) AS targets'
    )
    rows = await db.execute(query, {'slug': slug}, ['sp', 'targets'])
    if not rows:
        return None
    raw = graph.parse_agtype(rows[0]['sp'])
    if not isinstance(raw, dict):
        return None
    raw_dict: dict[str, typing.Any] = raw  # type: ignore[assignment]
    targets: list[str] = graph.parse_agtype(rows[0]['targets']) or []
    return _validate_policy_row(raw_dict, targets)


def _serialize_props(
    policy_props: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Serialize nested maps as JSON strings (AGE stores them as text)."""
    out = dict(policy_props)
    for key in _JSON_PROPS_KEYS:
        val = out.get(key)
        if val is not None and not isinstance(val, str):
            out[key] = json.dumps(val)
    return out


def _to_node_props(policy: PolicyType) -> dict[str, typing.Any]:
    """Map a policy to the flat property dict for AGE storage."""
    dumped = policy.model_dump(exclude={'targets'})
    return {k: v for k, v in dumped.items() if k in _NODE_PROPERTY_KEYS}


async def _enqueue_for_policy(
    client: OptionalValkeyClient,
    db: graph.Graph,
    policy: PolicyType,
    reason: score_queue.ChangeReason = 'policy_change',
) -> int:
    project_ids = await score_queue.affected_projects(db, policy)
    results = await asyncio.gather(
        *[
            score_queue.enqueue_recompute(client, pid, reason)
            for pid in project_ids
        ]
    )
    return sum(results)


@scoring_policies_router.get('/')
async def list_policies(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('scoring_policy:read')),
    ],
    category: str | None = None,
    enabled: bool | None = None,
    attribute_name: str | None = None,
) -> list[PolicyType]:
    parts: list[str] = []
    params: dict[str, typing.Any] = {}
    if category is not None:
        parts.append('sp.category = {category}')
        params['category'] = category
    if enabled is not None:
        parts.append('sp.enabled = {enabled}')
        params['enabled'] = enabled
    if attribute_name is not None:
        parts.append('sp.attribute_name = {attribute_name}')
        params['attribute_name'] = attribute_name
    where = (' WHERE ' + ' AND '.join(parts)) if parts else ''
    query: str = (
        'MATCH (sp:ScoringPolicy)'
        + where
        + ' OPTIONAL MATCH (sp)-[:TARGETS]->(pt:ProjectType)'
        ' RETURN sp, collect(pt.slug) AS targets ORDER BY sp.priority,'
        ' sp.slug'
    )
    rows = await db.execute(
        query,  # type: ignore[arg-type]
        params,
        ['sp', 'targets'],
    )
    out: list[PolicyType] = []
    for row in rows:
        raw = graph.parse_agtype(row['sp'])
        if not isinstance(raw, dict):
            continue
        raw_dict: dict[str, typing.Any] = raw  # type: ignore[assignment]
        targets: list[str] = graph.parse_agtype(row['targets']) or []
        policy = _validate_policy_row(raw_dict, targets)
        if policy is not None:
            out.append(policy)
    return out


@scoring_policies_router.get('/{slug}')
async def get_policy(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('scoring_policy:read')),
    ],
) -> PolicyType:
    policy = await load_policy(db, slug)
    if policy is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Scoring policy {slug!r} not found',
        )
    return policy


@scoring_policies_router.post('/', status_code=201)
async def create_policy(
    data: scoring_models.PolicyCreate,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('scoring_policy:write')
        ),
    ],
) -> PolicyType:
    payload = {
        k: v
        for k, v in data.model_dump(exclude={'targets'}).items()
        if v is not None or k == 'description'
    }
    payload.setdefault('category', 'attribute')
    try:
        policy = _POLICY_ADAPTER.validate_python(payload)
    except pydantic.ValidationError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    if data.targets:
        await _validate_targets(db, data.targets)
    props = _serialize_props(_to_node_props(policy))
    set_pairs = ', '.join(f'{k}: {{{k}}}' for k in props)
    create_q = 'CREATE (sp:ScoringPolicy {{' + set_pairs + '}}) RETURN sp'
    with conflict_on_unique_violation(
        f'Scoring policy {policy.slug!r} already exists',
    ):
        await db.execute(create_q, props, ['sp'])  # type: ignore[arg-type]
    if data.targets:
        await _create_target_edges(db, policy.slug, data.targets)
    refreshed = await load_policy(db, policy.slug)
    if refreshed is None:
        raise fastapi.HTTPException(
            status_code=500,
            detail='Failed to reload scoring policy after create',
        )
    await _enqueue_for_policy(valkey_client, db, refreshed)
    return refreshed


async def _validate_targets(db: graph.Graph, targets: list[str]) -> None:
    found_rows = await db.execute(
        'MATCH (pt:ProjectType) WHERE pt.slug IN {slugs}'
        ' RETURN collect(pt.slug) AS found',
        {'slugs': targets},
        ['found'],
    )
    found: list[str] = (
        graph.parse_agtype(found_rows[0]['found']) if found_rows else []
    ) or []
    missing = set(targets) - set(found)
    if missing:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Unknown project type(s): {sorted(missing)}',
        )


async def _create_target_edges(
    db: graph.Graph, slug: str, targets: list[str]
) -> None:
    link_q: typing.LiteralString = (
        'MATCH (sp:ScoringPolicy {{slug: {slug}}})'
        ' UNWIND {targets} AS ts'
        ' MATCH (pt:ProjectType {{slug: ts}})'
        ' MERGE (sp)-[:TARGETS]->(pt)'
    )
    await db.execute(link_q, {'slug': slug, 'targets': targets})


_POLICY_READONLY_PATHS: frozenset[str] = json_patch.READONLY_PATHS | frozenset(
    ['/slug', '/category']
)


@scoring_policies_router.patch('/{slug}')
async def update_policy(
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('scoring_policy:write')
        ),
    ],
) -> PolicyType:
    """Partially update a scoring policy using JSON Patch (RFC 6902).

    The fields ``slug`` and ``category`` are immutable. ``targets`` (a
    list of project-type slugs) may be replaced via a JSON Pointer
    ``/targets`` replace operation.
    """
    existing = await load_policy(db, slug)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Scoring policy {slug!r} not found',
        )
    document: dict[str, typing.Any] = existing.model_dump()
    patched = json_patch.apply_patch(
        document, operations, readonly_paths=_POLICY_READONLY_PATHS
    )
    new_targets: list[str] = patched.get('targets', existing.targets)
    try:
        validated = _POLICY_ADAPTER.validate_python(patched)
    except Exception as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid patch result: {exc}',
        ) from exc
    props = _serialize_props(_to_node_props(validated))
    # slug/category are immutable; don't write them back.
    props.pop('slug', None)
    props.pop('category', None)
    set_pairs = ', '.join(f'sp.{k} = {{{k}}}' for k in props)
    params: dict[str, typing.Any] = dict(props)
    params['slug'] = slug
    update_q = (
        'MATCH (sp:ScoringPolicy {{slug: {slug}}}) SET '
        + set_pairs
        + ' RETURN sp'
    )
    targets_changed = set(new_targets) != set(existing.targets)
    if targets_changed and new_targets:
        await _validate_targets(db, new_targets)
    await db.execute(update_q, params, ['sp'])  # type: ignore[arg-type]
    if targets_changed:
        clear_q: typing.LiteralString = (
            'MATCH (sp:ScoringPolicy {{slug: {slug}}})-[r:TARGETS]->()'
            ' DELETE r'
        )
        await db.execute(clear_q, {'slug': slug})
        if new_targets:
            await _create_target_edges(db, slug, new_targets)
    refreshed = await load_policy(db, slug)
    if refreshed is None:
        raise fastapi.HTTPException(
            status_code=500,
            detail='Failed to reload scoring policy after update',
        )
    await _enqueue_for_policy(valkey_client, db, refreshed)
    await _enqueue_for_policy(valkey_client, db, existing)
    return refreshed


@scoring_policies_router.delete('/{slug}', status_code=204)
async def delete_policy(
    slug: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('scoring_policy:delete')
        ),
    ],
) -> None:
    existing = await load_policy(db, slug)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Scoring policy {slug!r} not found',
        )
    await db.execute(
        'MATCH (sp:ScoringPolicy {{slug: {slug}}}) DETACH DELETE sp',
        {'slug': slug},
    )
    await _enqueue_for_policy(valkey_client, db, existing)
