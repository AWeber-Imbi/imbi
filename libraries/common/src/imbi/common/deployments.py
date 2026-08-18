"""``Deployment`` node reads and writes.

A deployment used to be a JSON element in the ``deployments`` array
property on the ``(:Release)-[:DEPLOYED_TO]->(:Environment)`` edge.  It
is now a node::

    (:Project)<-[:BELONGS_TO]-(d:Deployment)-[:TARGETS]->(:Environment)
    (:Release)-[:HAS_DEPLOYMENT]->(d)   # attached once resolved
    (:User)-[:PERFORMED]->(d)           # optional

which makes every update a single-node write rather than a
read-modify-write of the whole array, makes the in-flight backlog
queryable from Cypher, and lets an event be recorded against
``Project`` + ``Environment`` before (or without) a ``Release`` to
attach it to.

This module lives in ``imbi.common`` because both the API (writes and
the release-train reads) and the scoring engine (which derives a
project's per-environment status) need it.

``DEPLOYED_TO`` is still read: nothing back-fills the ~60k historical
array entries until the phase-3 migration, so every read path unions
node-based deployments with the legacy array entries.  Nothing writes
the array any more.

"""

import collections.abc as abc
import datetime
import logging
import typing

import nanoid

from imbi.common import graph, models

LOGGER = logging.getLogger(__name__)

DeploymentStatus = typing.Literal[
    'pending',
    'in_progress',
    'success',
    'failed',
    'rolled_back',
]

#: Plugin run status -> deployment status.  The ``DeploymentEvent``
#: vocabulary has no ``cancelled`` bucket, so a cancelled run reads as
#: a failed terminal -- what matters downstream is that it stopped.
RUN_STATUS_TO_STATUS: dict[str, DeploymentStatus] = {
    'queued': 'pending',
    'pending': 'pending',
    'in_progress': 'in_progress',
    'success': 'success',
    'failure': 'failed',
    'cancelled': 'failed',
}

#: How an upsert changed the node.  ``created`` is a brand-new node,
#: ``updated`` a status/note/URL change on an existing one, and
#: ``noop`` a replay that carried nothing new -- resync counts on the
#: distinction to keep its summary honest.  A ``noop`` still executes
#: the ``SET``, it just writes the values already there and leaves
#: ``updated_at`` and ``history`` alone.
UpsertOutcome = typing.Literal['created', 'updated', 'noop']


class UpsertResult(typing.NamedTuple):
    """Identity and disposition of an upserted ``Deployment``."""

    id: str
    outcome: UpsertOutcome


# Identity is ``(project, external_run_id)``: a remote run id names one
# rollout, so every writer that learns about it -- the promote watcher,
# the gateway webhook, resync, the sweeper -- converges on one node.
# The environment is *not* part of the MERGE key; a run id belongs to a
# single rollout, and matching on it alone means an event arriving with
# a different environment moves the node rather than forking it.  Moving
# means exactly one ``TARGETS`` edge, so the stale one is deleted rather
# than left alongside the new one -- ``MERGE`` only ever adds.
#
# The whole upsert is one statement so concurrent writers cannot
# interleave a check with an act.  As with the Release upsert this
# narrows the race rather than closing it -- AGE has no unique
# constraint -- but the window is a single MERGE wide.
#
# AGE has no ``ON CREATE SET`` / ``ON MATCH SET``, so the pre-write
# state is captured in ``WITH`` and the ``SET`` reads it from there:
# ``COALESCE`` for create-only properties, and the captured
# ``unchanged`` flag to keep a replay from bumping ``updated_at`` or
# appending to ``history``.
# ``WITH`` narrows scope, so every variable the clauses after it still
# need is carried through explicitly -- an unbound name in a later
# ``MERGE`` would create a node rather than fail.
_UPSERT_MERGE: typing.Final[typing.LiteralString] = """
    MERGE (p)<-[:BELONGS_TO]-(d:Deployment
          {{external_run_id: {external_run_id}}})
    WITH {carried}
    OPTIONAL MATCH (d)-[stale:TARGETS]->(old:Environment)
    WHERE id(old) <> id(e)
    DELETE stale
    WITH {carried}
    MERGE (d)-[:TARGETS]->(e)
"""

_UPSERT_CREATE: typing.Final[typing.LiteralString] = """
    CREATE (p)<-[:BELONGS_TO]-(d:Deployment {{id: {id}}})
    CREATE (d)-[:TARGETS]->(e)
"""

_UPSERT_TAIL: typing.Final[typing.LiteralString] = """
    WITH d,
         d.created_at AS prior_created,
         COALESCE(d.status, '') AS prior_status,
         (COALESCE(d.status, '') = {status}
          AND COALESCE(d.note, '') = COALESCE({note}, '')
          AND COALESCE(d.external_run_url, '')
              = COALESCE({external_run_url}, d.external_run_url, '')
          AND COALESCE(d.performed_by, '')
              = COALESCE({performed_by}, d.performed_by, '')) AS unchanged
    SET d.id = COALESCE(d.id, {id}),
        d.created_at = COALESCE(d.created_at, {timestamp}),
        d.status = {status},
        d.note = {note},
        d.external_run_url =
            COALESCE({external_run_url}, d.external_run_url),
        d.performed_by = COALESCE({performed_by}, d.performed_by),
        d.release_tag = COALESCE({release_tag}, d.release_tag),
        d.release_committish =
            COALESCE({release_committish}, d.release_committish),
        d.updated_at = CASE WHEN unchanged
            THEN COALESCE(d.updated_at, {timestamp}) ELSE {timestamp} END,
        d.history = CASE WHEN prior_status = {status}
            THEN COALESCE(d.history, [])
            ELSE COALESCE(d.history, []) + [{{status: {status},
                 timestamp: {timestamp}, source: {source}}}] END
    RETURN d.id AS id,
           prior_created AS prior_created,
           unchanged AS unchanged
"""


def _upsert_query(
    *, external_run_id: str | None, release_id: str | None
) -> typing.LiteralString:
    """Assemble the upsert for the identity the caller can offer."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    MATCH (e:Environment {{slug: {env_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    """
    if release_id is not None:
        query += """
    MATCH (p)-[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
    """
    if external_run_id:
        query += _UPSERT_MERGE.replace(
            '{carried}', 'd, e, r' if release_id is not None else 'd, e'
        )
    else:
        query += _UPSERT_CREATE
    if release_id is not None:
        query += """
    MERGE (r)-[:HAS_DEPLOYMENT]->(d)
    """
    return query + _UPSERT_TAIL


async def upsert_deployment(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    env_slug: str,
    status: DeploymentStatus,
    release_id: str | None = None,
    note: str | None = None,
    external_run_id: str | None = None,
    external_run_url: str | None = None,
    performed_by: str | None = None,
    release_tag: str | None = None,
    release_committish: str | None = None,
    timestamp: datetime.datetime | None = None,
    source: str = 'api',
) -> UpsertResult | None:
    """Create or advance the ``Deployment`` for this run.

    With an *external_run_id* the node is MERGEd on
    ``(project, external_run_id)`` so re-delivering the same webhook, or
    a watcher and a webhook both reporting the same rollout, converge on
    one node whose ``history`` records every transition.  Without one
    there is nothing to correlate on, so each call creates a node --
    matching the append-only semantics the array had for run-less
    callers.

    *release_id* attaches ``HAS_DEPLOYMENT``; ``None`` records the
    deployment against the project and environment alone, for a gateway
    event whose release cannot be resolved yet.  Such a caller passes
    the *release_tag* / *release_committish* it could not resolve, so
    :func:`attach_release` can finish the job when the Release turns
    up.

    A ``None`` *external_run_url* or *performed_by* means "unknown", not
    "clear": neither can blank a value another writer already recorded.

    Returns ``None`` when the project, environment, or named release
    does not exist, so the caller can tell a missing target from a
    write.
    """
    ts = (timestamp or datetime.datetime.now(datetime.UTC)).astimezone(
        datetime.UTC
    )
    rows = await db.execute(
        _upsert_query(external_run_id=external_run_id, release_id=release_id),
        {
            'project_id': project_id,
            'env_slug': env_slug,
            'org_slug': org_slug,
            'release_id': release_id,
            'external_run_id': external_run_id,
            'external_run_url': external_run_url,
            'performed_by': performed_by,
            'release_tag': release_tag,
            'release_committish': release_committish,
            'status': status,
            'note': note,
            'source': source,
            'id': nanoid.generate(),
            'timestamp': ts.isoformat(),
        },
        ['id', 'prior_created', 'unchanged'],
    )
    if not rows:
        return None
    node_id = str(graph.parse_agtype(rows[0]['id']))
    if graph.parse_agtype(rows[0]['prior_created']) is None:
        return UpsertResult(node_id, 'created')
    if graph.parse_agtype(rows[0]['unchanged']):
        return UpsertResult(node_id, 'noop')
    return UpsertResult(node_id, 'updated')


def node_to_event(
    props: abc.Mapping[str, typing.Any],
) -> models.DeploymentEvent | None:
    """Render a ``Deployment`` node as the event shape the API returns.

    The node holds the current state of one deployment; the event list
    the API has always returned holds one entry per deployment.  So the
    node maps to a single event carrying its latest status, timestamped
    with the last transition.  ``history`` stays on the node -- no
    response exposes it yet.
    """
    status = props.get('status')
    if status is None:
        return None
    try:
        return models.DeploymentEvent.model_validate(
            {
                'timestamp': props.get('updated_at')
                or props.get('created_at'),
                'status': status,
                'note': props.get('note'),
                'external_run_id': props.get('external_run_id'),
                'external_run_url': props.get('external_run_url'),
                'performed_by': props.get('performed_by'),
            }
        )
    except ValueError:
        LOGGER.warning(
            'Skipping malformed Deployment node %r', props.get('id')
        )
        return None


class ProjectDeployment(typing.NamedTuple):
    """One ``Deployment`` node with the nodes it hangs off."""

    project_id: str
    environment: dict[str, typing.Any]
    #: ``None`` until something attaches the deployment to a release --
    #: a gateway event whose release could not be resolved records the
    #: deployment anyway rather than dropping it.
    release: dict[str, typing.Any] | None
    event: models.DeploymentEvent


_BY_PROJECT_QUERY: typing.Final[typing.LiteralString] = """
MATCH (p:Project)<-[:BELONGS_TO]-(d:Deployment)-[:TARGETS]->(e:Environment)
WHERE p.id IN {project_ids}
OPTIONAL MATCH (r:Release)-[:HAS_DEPLOYMENT]->(d)
RETURN p.id AS project_id,
       e{{.slug, .name, .sort_order}} AS env,
       CASE WHEN r IS NULL THEN null ELSE r{{.*}} END AS release,
       d AS deployment
"""


async def deployments_by_project(
    db: graph.Graph, project_ids: abc.Sequence[str]
) -> list[ProjectDeployment]:
    """Return every ``Deployment`` recorded for *project_ids*.

    Callers union these with the legacy ``DEPLOYED_TO`` array entries;
    ordering is the caller's business because every one of them ranks
    by ``timestamp``.
    """
    if not project_ids:
        return []
    rows = await db.execute(
        _BY_PROJECT_QUERY,
        {'project_ids': list(project_ids)},
        ['project_id', 'env', 'release', 'deployment'],
    )
    out: list[ProjectDeployment] = []
    for row in rows:
        project_id = graph.parse_agtype(row.get('project_id'))
        env = graph.parse_agtype(row.get('env'))
        props = graph.parse_agtype(row.get('deployment'))
        if (
            not isinstance(project_id, str)
            or not isinstance(env, dict)
            or not isinstance(props, dict)
        ):
            continue
        event = node_to_event(typing.cast('dict[str, typing.Any]', props))
        if event is None:
            continue
        release = graph.parse_agtype(row.get('release'))
        out.append(
            ProjectDeployment(
                project_id,
                typing.cast('dict[str, typing.Any]', env),
                typing.cast('dict[str, typing.Any] | None', release),
                event,
            )
        )
    return out


def as_utc(value: datetime.datetime) -> datetime.datetime:
    """Return *value* as an aware UTC datetime.

    A ``Deployment`` node always stores an aware UTC timestamp, but a
    legacy array entry written without an offset parses naive, and
    comparing the two raises ``TypeError``.  Naive values are read as
    UTC, which is what every writer meant by them.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


def merge_events(
    *sources: abc.Iterable[models.DeploymentEvent],
) -> list[models.DeploymentEvent]:
    """Union event lists into one chronological history.

    The read paths all rank by ``timestamp``, and the legacy array is
    already stored oldest-first, so sorting is enough to interleave the
    two representations.
    """
    merged = [event for source in sources for event in source]
    merged.sort(key=lambda event: as_utc(event.timestamp))
    return merged


_CLOSE_IN_FLIGHT_QUERY: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {release_id}}})
      -[:HAS_DEPLOYMENT]->(d:Deployment)
      -[:TARGETS]->(:Environment {{slug: {env_slug}}})
WHERE d.status IN ['pending', 'in_progress']
SET d.status = {status},
    d.note = {note},
    d.updated_at = {timestamp},
    d.history = COALESCE(d.history, []) + [{{status: {status},
         timestamp: {timestamp}, source: {source}}}]
RETURN d.id AS id
"""


async def close_in_flight(
    db: graph.Graph,
    *,
    project_id: str,
    release_id: str,
    env_slug: str,
    status: DeploymentStatus,
    note: str | None = None,
    source: str = 'api',
    timestamp: datetime.datetime | None = None,
) -> list[str]:
    """Drive every unfinished deployment of a release terminal.

    For the writer that knows the outcome but not which run produced
    it -- a promote whose watch was abandoned, a rollout that timed
    out.  Returns the ids it closed.
    """
    ts = (timestamp or datetime.datetime.now(datetime.UTC)).astimezone(
        datetime.UTC
    )
    rows = await db.execute(
        _CLOSE_IN_FLIGHT_QUERY,
        {
            'project_id': project_id,
            'release_id': release_id,
            'env_slug': env_slug,
            'status': status,
            'note': note,
            'source': source,
            'timestamp': ts.isoformat(),
        },
        ['id'],
    )
    return [str(graph.parse_agtype(row['id'])) for row in rows]


class StuckDeployment(typing.NamedTuple):
    """An unfinished deployment the sweeper can chase to an answer."""

    id: str
    project_id: str
    org_slug: str
    env_slug: str
    external_run_id: str
    status: DeploymentStatus
    created_at: datetime.datetime
    #: ``None`` for a deployment recorded before its Release resolved.
    release_id: str | None
    release_tag: str | None
    release_committish: str | None


_STUCK_QUERY: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})<-[:BELONGS_TO]-(d:Deployment)
      -[:TARGETS]->(e:Environment)-[:BELONGS_TO]->(o:Organization)
WHERE d.status IN ['pending', 'in_progress']
      AND d.external_run_id IS NOT NULL
      AND COALESCE(d.updated_at, d.created_at) < {cutoff}
OPTIONAL MATCH (r:Release)-[:HAS_DEPLOYMENT]->(d)
RETURN d AS deployment,
       e.slug AS env_slug,
       o.slug AS org_slug,
       CASE WHEN r IS NULL THEN null ELSE r.id END AS release_id
"""


async def stuck_deployments(
    db: graph.Graph,
    *,
    project_id: str,
    cutoff: datetime.datetime,
) -> list[StuckDeployment]:
    """Return the project's deployments still running past *cutoff*.

    Only deployments carrying an ``external_run_id`` come back: without
    one there is no run for the sweeper to ask about, so nothing it
    could learn.
    """
    rows = await db.execute(
        _STUCK_QUERY,
        {
            'project_id': project_id,
            'cutoff': cutoff.astimezone(datetime.UTC).isoformat(),
        },
        ['deployment', 'env_slug', 'org_slug', 'release_id'],
    )
    out: list[StuckDeployment] = []
    for row in rows:
        props = graph.parse_agtype(row.get('deployment'))
        env_slug = graph.parse_agtype(row.get('env_slug'))
        org_slug = graph.parse_agtype(row.get('org_slug'))
        if (
            not isinstance(props, dict)
            or not isinstance(env_slug, str)
            or not isinstance(org_slug, str)
        ):
            continue
        created = props.get('created_at')
        if not isinstance(created, str):
            continue
        release_id = graph.parse_agtype(row.get('release_id'))
        out.append(
            StuckDeployment(
                id=str(props.get('id')),
                project_id=project_id,
                org_slug=org_slug,
                env_slug=env_slug,
                external_run_id=str(props.get('external_run_id')),
                status=typing.cast('DeploymentStatus', props.get('status')),
                created_at=datetime.datetime.fromisoformat(created),
                release_id=str(release_id) if release_id else None,
                release_tag=props.get('release_tag'),
                release_committish=props.get('release_committish'),
            )
        )
    return out


_ATTACH_QUERY: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})<-[:BELONGS_TO]-(d:Deployment
      {{id: {deployment_id}}})
MATCH (p)-[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
MERGE (r)-[:HAS_DEPLOYMENT]->(d)
RETURN d.id AS id
"""


async def attach_release(
    db: graph.Graph,
    *,
    project_id: str,
    deployment_id: str,
    release_id: str,
) -> bool:
    """Attach a deployment recorded before its release resolved."""
    rows = await db.execute(
        _ATTACH_QUERY,
        {
            'project_id': project_id,
            'deployment_id': deployment_id,
            'release_id': release_id,
        },
        ['id'],
    )
    return bool(rows)
