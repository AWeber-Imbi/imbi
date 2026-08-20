"""Read SBoM component usage facts from ClickHouse.

Phase three of the SBoM component migration. Every read that used to
answer "which components does this release use" by traversing
``USES_COMPONENT_RELEASE`` asks this module instead. The edge's fan-in
is what made those reads unusable -- counting the label outright fails
with ``could not resize shared memory segment`` -- and no amount of
Cypher rewriting fixes an unbounded incoming traversal.

What stays in the graph is identity and governance: the ``Component``
and ``ComponentRelease`` nodes, their statuses, advisories, notes, and
the project/team/environment topology. What moves here is the usage
fact, which is a per-release immutable snapshot and was never a good
fit for a graph edge.

Two graph primitives feed these reads and they are not interchangeable:

- The **org project set** -- non-archived project ids of an
  organization. Hundreds of ids, no fan-in. It scopes authorization,
  search, and the catalog totals, and it deliberately spans every
  release a project has ever had.
- The **deployment pointer set** -- the releases that
  ``(:Project)-[d:DEPLOYED_IN]->(:Environment)`` currently points at
  via ``d.current_release``. Around a thousand ids. It scopes the
  reports, which describe what is running now.

Substituting one for the other silently changes what a screen means, so
every function here takes the ids it needs rather than deriving them.

Every read resolves each release to exactly one batch before reading
its rows, using ``argMax(batch_id, (source = 'ingest', recorded_at))``.
``source`` leads the tuple deliberately: an ingest batch outranks a
backfill one whatever order the two land in, so a backfill running
beside live traffic can never displace a real SBoM. Reading
``release_components`` without that join reads every snapshot a release
has ever had, superseded ones included.
"""

from __future__ import annotations

import typing

from imbi.common import clickhouse, graph

#: Non-archived project ids of an organization -- the org project set.
#: Followed outward from the organization, so it is bounded by the
#: number of projects rather than by the component catalog.
ORG_PROJECT_IDS: typing.LiteralString = """
MATCH (:Organization {{slug: {org_slug}}})<-[:BELONGS_TO]-(:Team)
      <-[:OWNED_BY]-(p:Project)
WHERE coalesce(p.archived, false) = false
RETURN p.id AS project_id
"""

#: The deployment pointer set, with the topology each report row needs.
#: ``d.current_release`` is a property lookup, not an event replay, so
#: this stays cheap however long a project's deployment history is.
ORG_DEPLOYED_RELEASES: typing.LiteralString = """
MATCH (p:Project)-[d:DEPLOYED_IN]->(e:Environment)
MATCH (p)-[:OWNED_BY]->(t:Team)-[:BELONGS_TO]->
      (:Organization {{slug: {org_slug}}})
WHERE coalesce(p.archived, false) = false
OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
RETURN d.current_release AS release_id,
       p.id AS project_id,
       p.name AS project_name,
       p.slug AS project_slug,
       t.name AS team_name,
       t.slug AS team_slug,
       e.name AS environment_name,
       e.slug AS environment_slug,
       e.label_color AS environment_color,
       collect(DISTINCT pt.name) AS project_types
"""

#: Resolve each release of a set of projects to its winning batch.
_BATCHES_BY_PROJECT = (
    'SELECT release_id,'
    "       argMax(batch_id, (source = 'ingest', recorded_at)) AS batch_id"
    '  FROM imbi.release_component_batches'
    ' WHERE project_id IN {project_ids:Array(String)}'
    ' GROUP BY release_id'
)

#: The same resolution anchored on releases. Used by the reports, whose
#: scope is the deployment pointer set rather than whole projects.
_BATCHES_BY_RELEASE = (
    'SELECT release_id,'
    "       argMax(batch_id, (source = 'ingest', recorded_at)) AS batch_id"
    '  FROM imbi.release_component_batches'
    ' WHERE release_id IN {release_ids:Array(String)}'
    ' GROUP BY release_id'
)

_JOIN = (
    ' INNER JOIN ({batches}) AS b'
    ' ON c.release_id = b.release_id AND c.batch_id = b.batch_id'
)


def _by_project(select: str, where: str = '') -> str:
    """Compose a project-scoped read against the winning batches."""
    return (
        f'{select} FROM imbi.release_components AS c'
        + _JOIN.format(batches=_BATCHES_BY_PROJECT)
        + ' WHERE c.project_id IN {project_ids:Array(String)}'
        + where
    )


def _by_release(select: str, where: str = '') -> str:
    """Compose a release-scoped read against the winning batches."""
    return (
        f'{select} FROM imbi.release_components AS c'
        + _JOIN.format(batches=_BATCHES_BY_RELEASE)
        + ' WHERE c.release_id IN {release_ids:Array(String)}'
        + where
    )


async def org_project_ids(db: graph.Graph, org_slug: str) -> list[str]:
    """Return the org project set, or an empty list for an unknown org."""
    rows = await db.execute(
        ORG_PROJECT_IDS, {'org_slug': org_slug}, ['project_id']
    )
    # AGE hands back JSON-encoded scalars; ``str()`` on one of those
    # yields a quoted id that matches nothing in ClickHouse.
    decoded = (graph.parse_agtype(row.get('project_id')) for row in rows)
    return [str(value) for value in decoded if value]


async def component_ids_in_org(
    project_ids: list[str],
    component_ids: list[str] | None = None,
) -> set[str]:
    """Which component ids the org's projects currently depend on.

    Feeds the global search org scope, which needs the whole set, and
    package search, which needs only the subset its name match already
    produced. Passing *component_ids* narrows the aggregate to those,
    so a keystroke intersects against its own candidates rather than
    materialising the org's entire catalog to discard most of it.

    Unlike the traversal this replaces, the cost either way is one
    aggregate over the org's own rows rather than a fan-in from every
    ``ComponentRelease`` in the graph.
    """
    if not project_ids or component_ids == []:
        return set()
    where = ''
    params: dict[str, typing.Any] = {'project_ids': project_ids}
    if component_ids is not None:
        where = ' AND c.component_id IN {component_ids:Array(String)}'
        params['component_ids'] = component_ids
    rows = await clickhouse.query(
        _by_project('SELECT DISTINCT c.component_id AS component_id', where),
        params,
    )
    return {str(row['component_id']) for row in rows}


async def component_in_org(project_ids: list[str], component_id: str) -> bool:
    """Whether any of ``project_ids`` depends on ``component_id``.

    ``component_id`` leads ``release_components``' sort key, so this is
    a prefix seek rather than a scan however large the table gets.
    """
    if not project_ids:
        return False
    rows = await clickhouse.query(
        _by_project(
            'SELECT 1 AS hit',
            ' AND c.component_id = {component_id:String} LIMIT 1',
        ),
        {'project_ids': project_ids, 'component_id': component_id},
    )
    return bool(rows)


async def component_release_in_org(
    project_ids: list[str],
    component_id: str,
    component_release_id: str,
) -> bool:
    """Whether any of ``project_ids`` depends on that specific version.

    Takes the owning ``component_id`` as well as the version's own id
    purely to keep the sort-key prefix seek: ``component_release_id``
    is the fourth key column, so filtering on it alone scans. The
    caller already has the parent from the graph, where one
    ``HAS_RELEASE`` hop resolves it.
    """
    if not project_ids:
        return False
    rows = await clickhouse.query(
        _by_project(
            'SELECT 1 AS hit',
            ' AND c.component_id = {component_id:String}'
            ' AND c.component_release_id = {component_release_id:String}'
            ' LIMIT 1',
        ),
        {
            'project_ids': project_ids,
            'component_id': component_id,
            'component_release_id': component_release_id,
        },
    )
    return bool(rows)


async def search_counts(
    project_ids: list[str], component_ids: list[str]
) -> dict[str, tuple[int, int]]:
    """Return ``(version_count, project_count)`` per component id.

    ``uniqExact`` rather than ``uniq``: these are small cardinalities
    shown as literal numbers beside a package name, so an approximate
    count would be visibly wrong for no useful saving.
    """
    if not project_ids or not component_ids:
        return {}
    rows = await clickhouse.query(
        _by_project(
            'SELECT c.component_id AS component_id,'
            ' uniqExact(c.component_release_id) AS version_count,'
            ' uniqExact(c.project_id) AS project_count',
            ' AND c.component_id IN {component_ids:Array(String)}'
            ' GROUP BY c.component_id',
        ),
        {'project_ids': project_ids, 'component_ids': component_ids},
    )
    return {
        str(row['component_id']): (
            int(row['version_count']),
            int(row['project_count']),
        )
        for row in rows
    }


async def ecosystem_totals(project_ids: list[str]) -> dict[str, int]:
    """Component counts per ecosystem, scoped to the organization.

    Restores the scoping traded away for speed when this was a graph
    traversal: it counted every component in the catalog because
    traversing to the org cost 36.5s against 1.07s. The aggregate here
    is org-scoped and still cheap, so the chip labels describe what the
    reader's organization actually depends on again.
    """
    if not project_ids:
        return {}
    rows = await clickhouse.query(
        _by_project(
            'SELECT c.ecosystem AS ecosystem,'
            ' uniqExact(c.component_id) AS total',
            " AND c.ecosystem != '' GROUP BY c.ecosystem",
        ),
        {'project_ids': project_ids},
    )
    return {str(row['ecosystem']): int(row['total']) for row in rows}


async def component_usage(
    release_ids: list[str], component_id: str
) -> list[tuple[str, str, str]]:
    """``(release_id, component_release_id, version)`` for one package.

    Scoped to the deployment pointer set, so the result describes what
    is running now rather than every release that ever named the
    package. The caller joins each ``release_id`` back to the project,
    team, and environment it came from -- that topology stayed in the
    graph, and it is what produced the ids passed in here.
    """
    if not release_ids:
        return []
    rows = await clickhouse.query(
        _by_release(
            'SELECT DISTINCT c.release_id AS release_id,'
            ' c.component_release_id AS component_release_id,'
            ' c.version AS version',
            ' AND c.component_id = {component_id:String}',
        ),
        {'release_ids': release_ids, 'component_id': component_id},
    )
    return [
        (
            str(row['release_id']),
            str(row['component_release_id']),
            str(row['version']),
        )
        for row in rows
    ]


async def governed_usage(
    release_ids: list[str], component_release_ids: list[str]
) -> list[dict[str, str]]:
    """Deployed usages of a governed set of component versions.

    Both bounds come from the graph and both are small: the deployment
    pointer set on one side, and on the other the versions carrying a
    status or an advisory -- the anchor that kept Problem Packages
    starting from the governed set rather than from the catalog.
    """
    if not release_ids or not component_release_ids:
        return []
    rows = await clickhouse.query(
        _by_release(
            'SELECT DISTINCT c.release_id AS release_id,'
            ' c.component_id AS component_id,'
            ' c.component_release_id AS component_release_id,'
            ' c.version AS version',
            ' AND c.component_release_id IN'
            ' {component_release_ids:Array(String)}',
        ),
        {
            'release_ids': release_ids,
            'component_release_ids': component_release_ids,
        },
    )
    return [{key: str(value) for key, value in row.items()} for row in rows]


async def release_components(
    release_id: str,
) -> list[dict[str, typing.Any]]:
    """One release's currently-published component set.

    Returns the denormalized columns plus the ids the caller hydrates
    the rest from. ``license``, ``supplier``, ``hashes``, and the
    component identifiers are governance attributes of the
    ``ComponentRelease`` node and were never copied here, so the
    listing endpoint fetches them from the graph by id -- a bounded
    ``IN`` over one release's versions, not a traversal.
    """
    rows = await clickhouse.query(
        _by_release(
            'SELECT c.component_id AS component_id,'
            ' c.component_release_id AS component_release_id,'
            ' c.purl_name AS purl_name,'
            ' c.ecosystem AS ecosystem,'
            ' c.version AS version,'
            ' c.scope AS scope,'
            ' c.groups AS groups',
        ),
        {'release_ids': [release_id]},
    )
    return list(rows)
