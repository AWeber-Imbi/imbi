"""Vector similarity search endpoint."""

import logging
import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

search_router = fastapi.APIRouter(tags=['Search'])

_INITIAL_BATCH = 50
_BATCH_GROWTH = 2


class SearchResult(pydantic.BaseModel):
    """A single vector search result."""

    node_label: str
    node_id: str
    attribute: str
    chunk_text: str
    distance: float


async def _get_org_node_ids(
    db: graph.Graph,
    org_slug: str,
) -> set[str] | None:
    """Return node IDs for all nodes in the org, or None if org not found.

    Covers: the org itself, direct BELONGS_TO children (Team, Environment,
    ProjectType, ThirdPartyService, Tag, DocumentTemplate, LinkDefinition),
    Projects, Documents, Releases, Comments, and the Components reachable
    through the org's release dependency graph. Components are shared,
    cross-org identities, so they are scoped to those an org actually
    depends on rather than enumerated globally.
    """
    org_rows = await db.execute(
        'MATCH (o:Organization {{slug: {org_slug}}}) RETURN o.id AS org_id',
        {'org_slug': org_slug},
        columns=['org_id'],
    )
    if not org_rows:
        return None

    node_ids: set[str] = set()
    org_id = graph.parse_agtype(org_rows[0]['org_id'])
    if org_id:
        node_ids.add(org_id)

    for row in await db.execute(
        'MATCH (n)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
        ' RETURN n.id AS nid',
        {'org_slug': org_slug},
        columns=['nid'],
    ):
        nid = graph.parse_agtype(row['nid'])
        if nid:
            node_ids.add(nid)

    for row in await db.execute(
        'MATCH (p:Project)-[:OWNED_BY]->(:Team)-[:BELONGS_TO]->'
        '(:Organization {{slug: {org_slug}}}) RETURN p.id AS nid',
        {'org_slug': org_slug},
        columns=['nid'],
    ):
        nid = graph.parse_agtype(row['nid'])
        if nid:
            node_ids.add(nid)

    for row in await db.execute(
        'MATCH (d:Document)-[:ATTACHED_TO]->(:Project)-[:OWNED_BY]->'
        '(:Team)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
        ' RETURN d.id AS nid',
        {'org_slug': org_slug},
        columns=['nid'],
    ):
        nid = graph.parse_agtype(row['nid'])
        if nid:
            node_ids.add(nid)

    for row in await db.execute(
        'MATCH (:Organization {{slug: {org_slug}}})<-[:BELONGS_TO]-'
        '(:Team)<-[:OWNED_BY]-(:Project)-[:HAS_RELEASE]->(r:Release)'
        ' RETURN r.id AS nid',
        {'org_slug': org_slug},
        columns=['nid'],
    ):
        nid = graph.parse_agtype(row['nid'])
        if nid:
            node_ids.add(nid)

    for row in await db.execute(
        'MATCH (c:Comment)-[:IN_THREAD]->(:CommentThread)-[:ON_DOCUMENT]->'
        '(:Document)-[:ATTACHED_TO]->(:Project)-[:OWNED_BY]->(:Team)'
        '-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})'
        ' RETURN c.id AS nid',
        {'org_slug': org_slug},
        columns=['nid'],
    ):
        nid = graph.parse_agtype(row['nid'])
        if nid:
            node_ids.add(nid)

    for row in await db.execute(
        'MATCH (comp:Component)-[:HAS_RELEASE]->(:ComponentRelease)'
        '<-[:USES_COMPONENT_RELEASE]-(:Release)<-[:HAS_RELEASE]-(:Project)'
        '-[:OWNED_BY]->(:Team)-[:BELONGS_TO]->'
        '(:Organization {{slug: {org_slug}}})'
        ' RETURN comp.id AS nid',
        {'org_slug': org_slug},
        columns=['nid'],
    ):
        nid = graph.parse_agtype(row['nid'])
        if nid:
            node_ids.add(nid)

    return node_ids


@search_router.get('/search')
async def search(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('search:read'),
        ),
    ],
    q: typing.Annotated[str, fastapi.Query(min_length=1)],
    node_label: str | None = None,
    attribute: str | None = None,
    model: str = 'text',
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=100)] = 10,
    threshold: typing.Annotated[
        float | None,
        fastapi.Query(ge=0.0, le=2.0),
    ] = None,
) -> list[SearchResult]:
    """Search nodes by semantic similarity within an organization.

    Results are ordered by cosine distance ascending (most similar
    first). ``threshold`` is a distance ceiling: 0.0 = identical,
    2.0 = maximally dissimilar.
    """
    org_node_ids = await _get_org_node_ids(db, org_slug)
    if org_node_ids is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )

    out: list[SearchResult] = []
    batch_size = max(_INITIAL_BATCH, limit)
    seen: set[str] = set()

    while len(out) < limit:
        raw = await db.search(
            q,
            model_name=model,
            node_label=node_label,
            attribute=attribute,
            node_ids=org_node_ids,
            limit=batch_size,
            distance_threshold=threshold,
        )

        for r in raw:
            if r.node_id in seen:
                continue
            seen.add(r.node_id)
            out.append(
                SearchResult(
                    node_label=r.node_label,
                    node_id=r.node_id,
                    attribute=r.attribute,
                    chunk_text=r.chunk_text,
                    distance=r.distance,
                )
            )
            if len(out) == limit:
                break

        # Stop only when the backend returned fewer rows than requested,
        # which means the result set is exhausted.
        if len(raw) < batch_size:
            break

        batch_size *= _BATCH_GROWTH

    return out
