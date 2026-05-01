"""Scoring policy CRUD endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import typing

import fastapi
import psycopg.errors
from imbi_common import graph

from imbi_api.auth import permissions
from imbi_api.domain import scoring as scoring_models
from imbi_api.scoring import OptionalValkeyClient
from imbi_api.scoring import queue as score_queue

LOGGER = logging.getLogger(__name__)

scoring_policies_router = fastapi.APIRouter(
    prefix='/scoring/policies', tags=['Scoring']
)


_PARSE_PROPS_KEYS = (
    'value_score_map',
    'range_score_map',
)


def _parse_node(raw: dict[str, typing.Any]) -> dict[str, typing.Any]:
    out = dict(raw)
    for key in _PARSE_PROPS_KEYS:
        val = out.get(key)
        if isinstance(val, str):
            try:
                out[key] = json.loads(val)
            except (TypeError, ValueError):
                out[key] = None
    return out


async def load_policy(
    db: graph.Graph, slug: str
) -> scoring_models.ScoringPolicy | None:
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
    _raw_targets: list[str] = graph.parse_agtype(rows[0]['targets']) or []
    targets: list[str] = _raw_targets
    cleaned = _parse_node(raw_dict)
    cleaned['targets'] = targets
    return scoring_models.ScoringPolicy.model_validate(cleaned)


def _serialize_maps(
    policy_props: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    out = dict(policy_props)
    for key in _PARSE_PROPS_KEYS:
        val = out.get(key)
        if val is not None and not isinstance(val, str):
            out[key] = json.dumps(val)
    return out


async def _enqueue_for_policy(
    client: OptionalValkeyClient,
    db: graph.Graph,
    policy: scoring_models.ScoringPolicy,
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
) -> list[scoring_models.ScoringPolicy]:
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
    out: list[scoring_models.ScoringPolicy] = []
    for row in rows:
        raw = graph.parse_agtype(row['sp'])
        if not isinstance(raw, dict):
            continue
        raw_dict: dict[str, typing.Any] = raw  # type: ignore[assignment]
        _raw_targets: list[str] = graph.parse_agtype(row['targets']) or []
        targets: list[str] = _raw_targets
        cleaned = _parse_node(raw_dict)
        cleaned['targets'] = targets
        out.append(scoring_models.ScoringPolicy.model_validate(cleaned))
    return out


@scoring_policies_router.get('/{slug}')
async def get_policy(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('scoring_policy:read')),
    ],
) -> scoring_models.ScoringPolicy:
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
) -> scoring_models.ScoringPolicy:
    payload = data.model_dump(exclude={'targets'})
    policy = scoring_models.ScoringPolicy.model_validate(payload)
    props = _serialize_maps(policy.model_dump(exclude={'targets'}))
    create_q: typing.LiteralString = (
        'CREATE (sp:ScoringPolicy {{id: {id}, name: {name},'
        ' slug: {slug}, description: {description}, category: {category},'
        ' weight: {weight}, enabled: {enabled}, priority: {priority},'
        ' attribute_name: {attribute_name},'
        ' value_score_map: {value_score_map},'
        ' range_score_map: {range_score_map}}}) RETURN sp'
    )
    try:
        await db.execute(create_q, props, ['sp'])
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Scoring policy {policy.slug!r} already exists',
        ) from e
    if data.targets:
        found_rows = await db.execute(
            'MATCH (pt:ProjectType) WHERE pt.slug IN {slugs}'
            ' RETURN collect(pt.slug) AS found',
            {'slugs': data.targets},
            ['found'],
        )
        found: list[str] = (
            graph.parse_agtype(found_rows[0]['found']) if found_rows else []
        ) or []
        missing = set(data.targets) - set(found)
        if missing:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Unknown project type(s): {sorted(missing)}',
            )
        link_q: typing.LiteralString = (
            'MATCH (sp:ScoringPolicy {{slug: {slug}}})'
            ' UNWIND {targets} AS ts'
            ' MATCH (pt:ProjectType {{slug: ts}})'
            ' MERGE (sp)-[:TARGETS]->(pt)'
        )
        await db.execute(
            link_q, {'slug': policy.slug, 'targets': data.targets}
        )
    refreshed = await load_policy(db, policy.slug)
    if refreshed is None:
        raise fastapi.HTTPException(
            status_code=500,
            detail='Failed to reload scoring policy after create',
        )
    await _enqueue_for_policy(valkey_client, db, refreshed)
    return refreshed


@scoring_policies_router.patch('/{slug}')
async def update_policy(
    slug: str,
    data: scoring_models.PolicyUpdate,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('scoring_policy:write')
        ),
    ],
) -> scoring_models.ScoringPolicy:
    existing = await load_policy(db, slug)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Scoring policy {slug!r} not found',
        )
    updates = data.model_dump(exclude_unset=True, exclude={'targets'})
    if updates:
        merged = existing.model_dump(exclude={'targets'})
        merged.update(updates)
        validated = scoring_models.ScoringPolicy.model_validate(merged)
        props = _serialize_maps(
            validated.model_dump(exclude={'targets', 'slug', 'category'})
        )
        set_pairs = ', '.join(f'sp.{k} = {{{k}}}' for k in props)
        params: dict[str, typing.Any] = dict(props)
        params['slug'] = slug
        update_q = (
            'MATCH (sp:ScoringPolicy {{slug: {slug}}}) SET '
            + set_pairs
            + ' RETURN sp'
        )
        await db.execute(update_q, params, ['sp'])  # type: ignore[arg-type]
    if data.targets is not None:
        if data.targets:
            found_rows = await db.execute(
                'MATCH (pt:ProjectType) WHERE pt.slug IN {slugs}'
                ' RETURN collect(pt.slug) AS found',
                {'slugs': data.targets},
                ['found'],
            )
            found: list[str] = (
                graph.parse_agtype(found_rows[0]['found'])
                if found_rows
                else []
            ) or []
            missing = set(data.targets) - set(found)
            if missing:
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=f'Unknown project type(s): {sorted(missing)}',
                )
        clear_q: typing.LiteralString = (
            'MATCH (sp:ScoringPolicy {{slug: {slug}}})-[r:TARGETS]->()'
            ' DELETE r'
        )
        await db.execute(clear_q, {'slug': slug})
        if data.targets:
            link_q: typing.LiteralString = (
                'MATCH (sp:ScoringPolicy {{slug: {slug}}})'
                ' UNWIND {targets} AS ts'
                ' MATCH (pt:ProjectType {{slug: ts}})'
                ' MERGE (sp)-[:TARGETS]->(pt)'
            )
            await db.execute(link_q, {'slug': slug, 'targets': data.targets})
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
