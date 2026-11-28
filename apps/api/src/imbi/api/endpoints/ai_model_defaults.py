"""The default model of an organization and of its teams (ADR 0018).

A ``USES_DEFAULT_MODEL`` edge from an ``Organization`` or a ``Team`` to
an ``AIModel``, at most one for each source node.
:mod:`imbi.common.llm.resolve` reads it.
"""

import typing

import fastapi
import pydantic

from imbi.api.auth import organizations, permissions
from imbi.common import graph

#: Mounted under ``/organizations/{org_slug}``.
ai_model_defaults_router = fastapi.APIRouter(
    tags=['AI Models'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)

OrgId = organizations.MemberOrgId

_ORG_DEFAULT_QUERY: typing.LiteralString = """
MATCH (s:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (s)-[:USES_DEFAULT_MODEL]->(m:AIModel)
RETURN s.id AS id, m.slug AS slug
"""

_TEAM_DEFAULT_QUERY: typing.LiteralString = """
MATCH (s:Team {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (s)-[:USES_DEFAULT_MODEL]->(m:AIModel)
RETURN s.id AS id, m.slug AS slug
"""

#: A model of the organization. ``team`` is set only when the team
#: ``{team_id}`` may use the model.
_DEFAULT_CANDIDATE_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{id: {org_id}}})
OPTIONAL MATCH (m)-[:ALLOWED_FOR]->(t:Team {{id: {team_id}}})
RETURN m.id AS id, m.model_type AS model_type,
       m.access_scope AS access_scope, t.id AS team
"""

_CLEAR_DEFAULT_QUERIES: dict[str, typing.LiteralString] = {
    'Organization': """
    MATCH (:Organization {{id: {id}}})-[r:USES_DEFAULT_MODEL]->()
    DELETE r
    """,
    'Team': """
    MATCH (:Team {{id: {id}}})-[r:USES_DEFAULT_MODEL]->()
    DELETE r
    """,
}

_LINK_DEFAULT_QUERIES: dict[str, typing.LiteralString] = {
    'Organization': """
    MATCH (s:Organization {{id: {id}}})
    MATCH (m:AIModel {{id: {model}}})
    CREATE (s)-[:USES_DEFAULT_MODEL]->(m)
    """,
    'Team': """
    MATCH (s:Team {{id: {id}}})
    MATCH (m:AIModel {{id: {model}}})
    CREATE (s)-[:USES_DEFAULT_MODEL]->(m)
    """,
}


class DefaultAIModel(pydantic.BaseModel):
    """The default model of an organization or a team. ``None`` is no
    default."""

    slug: str | None = None


async def _read_default(
    db: graph.Graph, query: typing.LiteralString, params: dict[str, str]
) -> tuple[str, str | None] | None:
    """Return the id of the source node and the slug of its default."""
    records = await db.execute(query, params, ['id', 'slug'])
    if not records:
        return None
    slug = graph.parse_agtype(records[0]['slug'])
    return str(graph.parse_agtype(records[0]['id'])), slug


async def _default_candidate(
    db: graph.Graph, org_id: str, slug: str, team_id: str | None
) -> str:
    """Return the id of the model ``slug`` of the organization when it
    can be a default (of the team ``team_id``).

    Raises:
        422: No such model, a decision model, or a ``restricted`` model
            that does not allow the team.

    """
    records = await db.execute(
        _DEFAULT_CANDIDATE_QUERY,
        {'slug': slug, 'org_id': org_id, 'team_id': team_id},
        ['id', 'model_type', 'access_scope', 'team'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=422, detail=f'AI model {slug!r} is not in the catalog'
        )
    row = {k: graph.parse_agtype(v) for k, v in records[0].items()}
    if row['model_type'] == 'decision':
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'AI model {slug!r} is a decision model; a default '
            'model must be generative',
        )
    if (
        team_id is not None
        and row['access_scope'] == 'restricted'
        and row['team'] is None
    ):
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'AI model {slug!r} is restricted to teams that do not '
            'include this team',
        )
    return str(row['id'])


async def _write_default(
    db: graph.Graph,
    org_id: str,
    label: typing.Literal['Organization', 'Team'],
    source_id: str,
    slug: str | None,
) -> None:
    """Replace the default of a source node. ``None`` clears it."""
    model = (
        None
        if slug is None
        else await _default_candidate(
            db, org_id, slug, source_id if label == 'Team' else None
        )
    )

    async def work(execute: graph.CypherExecute) -> None:
        await execute(_CLEAR_DEFAULT_QUERIES[label], {'id': source_id})
        if model is not None:
            await execute(
                _LINK_DEFAULT_QUERIES[label], {'id': source_id, 'model': model}
            )

    await db.locked(f'default-ai-model:{source_id}', work)


def _org_not_found(org_slug: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=404,
        detail=f'Organization with slug {org_slug!r} not found',
    )


def _team_not_found(slug: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=404, detail=f'Team with slug {slug!r} not found'
    )


@ai_model_defaults_router.get(
    '/default-ai-model', response_model=DefaultAIModel
)
async def get_organization_default_ai_model(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> DefaultAIModel:
    """Get the default model of the organization.

    Raises:
        404: No such organization.

    """
    _ = auth
    found = await _read_default(db, _ORG_DEFAULT_QUERY, {'org_slug': org_slug})
    if found is None:
        raise _org_not_found(org_slug)
    return DefaultAIModel(slug=found[1])


@ai_model_defaults_router.put(
    '/default-ai-model', response_model=DefaultAIModel
)
async def set_organization_default_ai_model(
    org_slug: str,
    org_id: OrgId,
    data: DefaultAIModel,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:update')),
    ],
) -> DefaultAIModel:
    """Set the default model of the organization. A ``null`` slug
    clears it.

    Raises:
        404: No such organization.
        422: No such model, or a decision model.

    """
    _ = auth
    found = await _read_default(db, _ORG_DEFAULT_QUERY, {'org_slug': org_slug})
    if found is None:
        raise _org_not_found(org_slug)
    await _write_default(db, org_id, 'Organization', found[0], data.slug)
    return data


@ai_model_defaults_router.get(
    '/teams/{slug}/default-ai-model', response_model=DefaultAIModel
)
async def get_team_default_ai_model(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> DefaultAIModel:
    """Get the default model of a team.

    Raises:
        404: No such team.

    """
    _ = auth
    found = await _read_default(
        db, _TEAM_DEFAULT_QUERY, {'org_slug': org_slug, 'slug': slug}
    )
    if found is None:
        raise _team_not_found(slug)
    return DefaultAIModel(slug=found[1])


@ai_model_defaults_router.put(
    '/teams/{slug}/default-ai-model', response_model=DefaultAIModel
)
async def set_team_default_ai_model(
    org_slug: str,
    org_id: OrgId,
    slug: str,
    data: DefaultAIModel,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> DefaultAIModel:
    """Set the default model of a team. A ``null`` slug clears it.

    Raises:
        404: No such team.
        422: No such model, a decision model, or a ``restricted`` model
            that does not allow the team.

    """
    _ = auth
    found = await _read_default(
        db, _TEAM_DEFAULT_QUERY, {'org_slug': org_slug, 'slug': slug}
    )
    if found is None:
        raise _team_not_found(slug)
    await _write_default(db, org_id, 'Team', found[0], data.slug)
    return data


__all__ = ['ai_model_defaults_router']
