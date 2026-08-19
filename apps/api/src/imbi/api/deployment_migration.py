"""Phase-3 deployment data cleanup.

Three maintenance operations over the graph the deployment rework left
behind, each with a read-only report mode:

1. **Duplicate-Release merge** -- fold sibling ``Release`` nodes that
   share a ``(project, tag)`` into one.  Phase 1 (tag-first identity)
   stopped new duplicates; this cleans up the ~2,200 nodes the old
   committish-first identity accumulated.
2. **Array-to-node migration** -- unnest the legacy ``deployments``
   JSON array on each ``DEPLOYED_TO`` edge into ``Deployment`` nodes
   (the phase-2 model), collapsing entries that share an
   ``external_run_id`` into one node whose ``history`` keeps every
   transition.
3. **Orphan-Release purge** -- find tagged ``Release`` nodes whose tag
   never came to exist on the remote (pre-#216 failed dispatches) and,
   in purge mode, delete them along with their ``Blocker`` nodes.

Run order matters and is documented on the registry entries: the merge
first (so migrated nodes land on surviving Releases), the migration
second, the phase-2 ``deployment-sweep`` third (to drain what the
migration surfaces), and the orphan check last.  Nothing enforces the
order -- every operation is correct alone -- it just minimizes rework.

The read paths keep unioning ``DEPLOYED_TO`` array entries with
``Deployment`` nodes until the migration has run in every environment;
retiring the array read path is a follow-up, not part of this module.
"""

from __future__ import annotations

import collections.abc as abc
import datetime
import hashlib
import json
import logging
import typing

import nanoid

from imbi.common import deployments as deployment_nodes
from imbi.common import graph, models, versioning

LOGGER = logging.getLogger(__name__)

#: ``source`` stamped on ``history`` transitions the migration writes
#: and ``origin`` on the nodes it creates, so migrated data stays
#: distinguishable from live writers.
MIGRATION_SOURCE = 'migration'

# ---------------------------------------------------------------------------
# Duplicate-Release merge
# ---------------------------------------------------------------------------

#: Release properties a merge may copy from a duplicate onto the
#: survivor when the survivor's own value is empty.  Never anything
#: identity-bearing (``id``, ``tag``, ``committish``) and never the
#: block flags (the blocker migration owns those).
MERGEABLE_PROPERTIES: tuple[str, ...] = (
    'title',
    'description',
    'links',
    'promoted_committish',
    'workflow_run_id',
    'workflow_run_url',
    'author',
    'created_by',
)


class DupMergeSummary(typing.NamedTuple):
    """What one project's duplicate-Release merge did (or would do)."""

    groups: int = 0
    merged: int = 0
    repointed_deployments: int = 0
    repointed_blockers: int = 0
    pointer_updates: int = 0
    filled_properties: int = 0
    #: Groups whose survivor fell back to "newest" because the remote
    #: could not say what the tag points at.
    unresolved_tags: int = 0


_TAGGED_RELEASES: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.tag IS NOT NULL
RETURN r{{.*}} AS release
"""

_RELEASE_EDGES: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {release_id}}})
      -[d:DEPLOYED_TO]->(e:Environment)-[:BELONGS_TO]->(o:Organization)
RETURN e.slug AS env_slug, o.slug AS org_slug,
       d.deployments AS deployments
"""

_WRITE_SURVIVOR_EDGE: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(s:Release {{id: {survivor_id}}})
MATCH (e:Environment {{slug: {env_slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MERGE (s)-[d:DEPLOYED_TO]->(e)
SET d.deployments = {deployments}
RETURN s.id AS id
"""

_REPOINT_HAS_DEPLOYMENT: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {loser_id}}})
      -[h:HAS_DEPLOYMENT]->(d:Deployment)
MATCH (p)-[:HAS_RELEASE]->(s:Release {{id: {survivor_id}}})
MERGE (s)-[:HAS_DEPLOYMENT]->(d)
DELETE h
RETURN d.id AS id
"""

_REPOINT_BLOCKED_BY: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {loser_id}}})
      -[h:BLOCKED_BY]->(b:Blocker)
MATCH (p)-[:HAS_RELEASE]->(s:Release {{id: {survivor_id}}})
MERGE (s)-[:BLOCKED_BY]->(b)
DELETE h
RETURN b.id AS id
"""

_REPOINT_CURRENT_RELEASE: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[d:DEPLOYED_IN]->(:Environment)
WHERE d.current_release = {loser_id}
SET d.current_release = {survivor_id}
RETURN d.current_release AS id
"""

_DELETE_MERGED_RELEASE: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
DETACH DELETE r
"""


def _release_props(
    rows: list[dict[str, typing.Any]],
) -> list[dict[str, typing.Any]]:
    """Parse the tagged-release rows into property dicts."""
    out: list[dict[str, typing.Any]] = []
    for row in rows:
        props = graph.parse_agtype(row.get('release'))
        if isinstance(props, dict):
            typed = typing.cast('dict[str, typing.Any]', props)
            if typed.get('id'):
                out.append(typed)
    return out


def _newest(group: list[dict[str, typing.Any]]) -> dict[str, typing.Any]:
    """The newest node, tie-broken on id so re-runs pick the same one."""
    return max(
        group,
        key=lambda n: (
            str(n.get('created_at') or ''),
            str(n.get('id') or ''),
        ),
    )


def _pick_survivor(
    group: list[dict[str, typing.Any]], resolved_sha: str | None
) -> tuple[dict[str, typing.Any], bool]:
    """Choose which duplicate keeps the tag's identity.

    The node whose committish (or ``promoted_committish``) agrees with
    what the tag actually points at wins; without an answer from the
    remote -- or when no node agrees -- the newest node wins.  Returns
    the survivor and whether the choice was remote-confirmed.
    """
    if resolved_sha:
        short = versioning.short_committish(resolved_sha)
        matches = [
            node
            for node in group
            if node.get('committish') == short
            or node.get('promoted_committish') == short
        ]
        if matches:
            return _newest(matches), True
    return _newest(group), False


def _is_empty(field: str, value: object) -> bool:
    if field == 'links':
        return value in (None, '', '[]')
    return value in (None, '')


def _property_fills(
    survivor: dict[str, typing.Any],
    losers: list[dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    """Mergeable properties the survivor lacks and some duplicate has.

    Newest duplicate wins when several carry a value -- the same
    recency rule the survivor choice itself falls back to.
    """
    fills: dict[str, typing.Any] = {}
    for field in MERGEABLE_PROPERTIES:
        if not _is_empty(field, survivor.get(field)):
            continue
        for loser in sorted(
            losers,
            key=lambda n: (
                str(n.get('created_at') or ''),
                str(n.get('id') or ''),
            ),
            reverse=True,
        ):
            value = loser.get(field)
            if not _is_empty(field, value):
                fills[field] = value
                break
    return fills


def _fill_query(fields: list[str]) -> str:
    """A no-clobber ``SET`` for exactly the fields being filled.

    Field names come from :data:`MERGEABLE_PROPERTIES`, never from
    data.  Each ``SET`` re-checks emptiness so a concurrent writer that
    filled the property first is left alone.
    """
    clauses: list[str] = []
    for field in fields:
        empty = "'[]'" if field == 'links' else "''"
        clauses.append(
            f'r.{field} = CASE WHEN COALESCE(r.{field}, {empty}) = {empty} '
            f'THEN {{{field}}} ELSE r.{field} END'
        )
    return (
        'MATCH (:Project {{id: {project_id}}})'
        '-[:HAS_RELEASE]->(r:Release {{id: {release_id}}})\n'
        'SET ' + ',\n    '.join(clauses) + '\nRETURN r.id AS id'
    )


def _array_entries(raw: object) -> list[dict[str, typing.Any]]:
    """The ``deployments`` edge property as a list of entry dicts.

    Tolerant on purpose: undecodable JSON and non-dict entries yield
    nothing rather than failing the merge -- the strict validation pass
    belongs to the migration, which reports what it skipped.
    """
    value = graph.parse_agtype(raw)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    items = typing.cast('list[object]', value)
    return [
        typing.cast('dict[str, typing.Any]', item)
        for item in items
        if isinstance(item, dict)
    ]


def _merge_arrays(
    *sources: list[dict[str, typing.Any]],
) -> list[dict[str, typing.Any]]:
    """Union entry lists, dropping exact duplicates, oldest first."""
    merged: list[dict[str, typing.Any]] = []
    seen: set[str] = set()
    for source in sources:
        for entry in source:
            key = json.dumps(entry, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                merged.append(entry)
    merged.sort(key=lambda entry: str(entry.get('timestamp') or ''))
    return merged


async def _edges_by_env(
    db: graph.Graph, project_id: str, release_id: str
) -> dict[str, tuple[str, list[dict[str, typing.Any]]]]:
    """One release's ``DEPLOYED_TO`` edges: env slug -> (org, entries)."""
    rows = await db.execute(
        _RELEASE_EDGES,
        {'project_id': project_id, 'release_id': release_id},
        ['env_slug', 'org_slug', 'deployments'],
    )
    out: dict[str, tuple[str, list[dict[str, typing.Any]]]] = {}
    for row in rows:
        env_slug = graph.parse_agtype(row.get('env_slug'))
        org_slug = graph.parse_agtype(row.get('org_slug'))
        if not isinstance(env_slug, str) or not isinstance(org_slug, str):
            continue
        out[env_slug] = (org_slug, _array_entries(row.get('deployments')))
    return out


async def merge_duplicate_releases(
    db: graph.Graph,
    project_id: str,
    *,
    org_slug: str,
    dry_run: bool = False,
) -> DupMergeSummary:
    """Fold duplicate ``(project, tag)`` Release nodes into one.

    The survivor is the node whose committish matches what the tag
    actually points at on the remote (via the deployment plugin's
    ``resolve_committish``); when the remote cannot answer, the newest
    node.  Everything hanging off a duplicate moves to the survivor:
    ``HAS_DEPLOYMENT`` and ``BLOCKED_BY`` edges are re-pointed,
    ``DEPLOYED_TO`` deployment arrays are unioned per environment,
    ``DEPLOYED_IN.current_release`` pointers naming a duplicate are
    rewritten, and mergeable properties the survivor lacks are filled
    in (never overwritten -- see the release-notes no-clobber history).
    The emptied duplicate is then ``DETACH DELETE``\\ d.

    Idempotent: a re-run finds no group with more than one node.  With
    *dry_run* set nothing is written; the plan is logged per group and
    the summary counts what a real run would merge.
    """
    from imbi.api.endpoints import project_deployments

    rows = await db.execute(
        _TAGGED_RELEASES, {'project_id': project_id}, ['release']
    )
    groups: dict[str, list[dict[str, typing.Any]]] = {}
    for props in _release_props(rows):
        groups.setdefault(str(props['tag']), []).append(props)
    duplicates = {
        tag: group for tag, group in groups.items() if len(group) > 1
    }
    if not duplicates:
        return DupMergeSummary()

    resolved = await project_deployments.resolve_remote_tags(
        db,
        org_slug=org_slug,
        project_id=project_id,
        tags=sorted(duplicates),
    )

    merged = repointed_deployments = repointed_blockers = 0
    pointer_updates = filled = unresolved = 0
    for tag in sorted(duplicates):
        group = duplicates[tag]
        answer = resolved.get(tag) if resolved else None
        sha = answer if answer not in (None, 'absent', 'error') else None
        if sha is None:
            unresolved += 1
        survivor, confirmed = _pick_survivor(group, sha)
        survivor_id = str(survivor['id'])
        losers = [n for n in group if str(n['id']) != survivor_id]
        fills = _property_fills(survivor, losers)
        if dry_run:
            LOGGER.info(
                'release-dup-merge dry run: project %s tag %s keeps %s '
                '(%s), folds %s, fills %s',
                project_id,
                tag,
                survivor_id,
                'remote-confirmed' if confirmed else 'newest',
                [str(n['id']) for n in losers],
                sorted(fills) or 'nothing',
            )
            merged += len(losers)
            filled += len(fills)
            continue
        if fills:
            fields = sorted(fills)
            await db.execute(
                _fill_query(fields),
                {
                    'project_id': project_id,
                    'release_id': survivor_id,
                    **{field: fills[field] for field in fields},
                },
                ['id'],
            )
            filled += len(fills)
        survivor_edges = await _edges_by_env(db, project_id, survivor_id)
        for loser in losers:
            loser_id = str(loser['id'])
            moved = await db.execute(
                _REPOINT_HAS_DEPLOYMENT,
                {
                    'project_id': project_id,
                    'loser_id': loser_id,
                    'survivor_id': survivor_id,
                },
                ['id'],
            )
            repointed_deployments += len(moved)
            blocked = await db.execute(
                _REPOINT_BLOCKED_BY,
                {
                    'project_id': project_id,
                    'loser_id': loser_id,
                    'survivor_id': survivor_id,
                },
                ['id'],
            )
            repointed_blockers += len(blocked)
            for env_slug, (edge_org, entries) in (
                await _edges_by_env(db, project_id, loser_id)
            ).items():
                _, existing = survivor_edges.get(env_slug, (edge_org, []))
                combined = _merge_arrays(existing, entries)
                await db.execute(
                    _WRITE_SURVIVOR_EDGE,
                    {
                        'project_id': project_id,
                        'survivor_id': survivor_id,
                        'env_slug': env_slug,
                        'org_slug': edge_org,
                        'deployments': json.dumps(combined),
                    },
                    ['id'],
                )
                survivor_edges[env_slug] = (edge_org, combined)
            pointers = await db.execute(
                _REPOINT_CURRENT_RELEASE,
                {
                    'project_id': project_id,
                    'loser_id': loser_id,
                    'survivor_id': survivor_id,
                },
                ['id'],
            )
            pointer_updates += len(pointers)
            await db.execute(
                _DELETE_MERGED_RELEASE,
                {'project_id': project_id, 'release_id': loser_id},
                [],
            )
            merged += 1

    summary = DupMergeSummary(
        groups=len(duplicates),
        merged=merged,
        repointed_deployments=repointed_deployments,
        repointed_blockers=repointed_blockers,
        pointer_updates=pointer_updates,
        filled_properties=filled,
        unresolved_tags=unresolved,
    )
    LOGGER.info(
        'release-dup-merge%s: project %s %s',
        ' dry run' if dry_run else '',
        project_id,
        summary,
    )
    return summary


# ---------------------------------------------------------------------------
# Array-to-node migration
# ---------------------------------------------------------------------------


class MigrationSummary(typing.NamedTuple):
    """What one project's array-to-node migration did (or would do)."""

    edges: int = 0
    entries: int = 0
    #: Array entries that failed ``DeploymentEvent`` validation and
    #: were skipped (logged, never written).
    malformed: int = 0
    created: int = 0
    #: Run-id groups whose ``Deployment`` node already existed -- a
    #: live writer (or an earlier run of this migration) beat us to
    #: it, so the node's own state is left authoritative.
    existing: int = 0
    cleared_edges: int = 0


class _ArrayEntry(typing.NamedTuple):
    """One legacy array entry with the edge context it came from."""

    event: models.DeploymentEvent
    release_id: str
    release_tag: str | None
    release_committish: str | None
    env_slug: str
    org_slug: str


_MIGRATABLE_EDGES: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
      -[d:DEPLOYED_TO]->(e:Environment)-[:BELONGS_TO]->(o:Organization)
WHERE d.deployments IS NOT NULL
RETURN r.id AS release_id, r.tag AS tag, r.committish AS committish,
       e.slug AS env_slug, o.slug AS org_slug,
       d.deployments AS deployments
"""

_EXISTING_RUN_NODES: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})<-[:BELONGS_TO]-(d:Deployment)
WHERE d.external_run_id IN {run_ids}
RETURN d.external_run_id AS run_id
"""

# AGE has no ON CREATE SET, so the pre-write state is captured in WITH
# and the SET guards on it: a node that already exists keeps its own
# status, note, timestamps, and history -- a live writer's answer is
# fresher than the array's.  COALESCE fills what the node never had.
_MIGRATE_RUN_NODE: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
MERGE (p)<-[:BELONGS_TO]-(d:Deployment
      {{external_run_id: {external_run_id}}})
WITH d, d.created_at AS prior_created
SET d.id = COALESCE(d.id, {id}),
    d.origin = COALESCE(d.origin, {source}),
    d.created_at = CASE WHEN prior_created IS NULL
        OR prior_created > {first_ts} THEN {first_ts}
        ELSE prior_created END,
    d.status = CASE WHEN prior_created IS NULL
        THEN {status} ELSE d.status END,
    d.note = CASE WHEN prior_created IS NULL THEN {note} ELSE d.note END,
    d.external_run_url = COALESCE(d.external_run_url, {external_run_url}),
    d.performed_by = COALESCE(d.performed_by, {performed_by}),
    d.release_tag = COALESCE(d.release_tag, {release_tag}),
    d.release_committish =
        COALESCE(d.release_committish, {release_committish}),
    d.updated_at = CASE WHEN prior_created IS NULL
        THEN {last_ts} ELSE d.updated_at END,
    d.history = CASE WHEN prior_created IS NULL
        THEN {history} ELSE COALESCE(d.history, []) END
RETURN d.id AS id, prior_created AS prior_created
"""

# Attaching is keyed off "has no TARGETS yet" rather than off node
# freshness so a run interrupted between node write and attach heals on
# the next pass.  A node a live writer created already targets its
# environment, so this never adds a second edge or moves one.
_ATTACH_IF_UNTARGETED: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
      <-[:BELONGS_TO]-(d:Deployment {{id: {deployment_id}}})
MATCH (e:Environment {{slug: {env_slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (p)-[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
OPTIONAL MATCH (d)-[t:TARGETS]->(:Environment)
WITH d, e, r, count(t) AS targets
WHERE targets = 0
MERGE (d)-[:TARGETS]->(e)
MERGE (r)-[:HAS_DEPLOYMENT]->(d)
RETURN d.id AS id
"""

# Entries without a run id had append-only, uncorrelatable semantics:
# each is its own deployment, so each becomes its own node under a
# deterministic id -- what makes a re-run (or a crash-and-retry) land
# on the same node instead of minting a duplicate.
_MIGRATE_ENTRY_NODE: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
MATCH (e:Environment {{slug: {env_slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (p)-[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
MERGE (p)<-[:BELONGS_TO]-(d:Deployment {{id: {id}}})
WITH d, e, r, d.created_at AS prior_created
SET d.origin = COALESCE(d.origin, {source}),
    d.created_at = COALESCE(d.created_at, {timestamp}),
    d.status = CASE WHEN prior_created IS NULL
        THEN {status} ELSE d.status END,
    d.note = CASE WHEN prior_created IS NULL THEN {note} ELSE d.note END,
    d.external_run_url = COALESCE(d.external_run_url, {external_run_url}),
    d.performed_by = COALESCE(d.performed_by, {performed_by}),
    d.release_tag = COALESCE(d.release_tag, {release_tag}),
    d.release_committish =
        COALESCE(d.release_committish, {release_committish}),
    d.updated_at = COALESCE(d.updated_at, {timestamp}),
    d.history = CASE WHEN prior_created IS NULL
        THEN {history} ELSE COALESCE(d.history, []) END
MERGE (d)-[:TARGETS]->(e)
MERGE (r)-[:HAS_DEPLOYMENT]->(d)
RETURN d.id AS id, prior_created AS prior_created
"""

# SET to NULL removes the property in AGE; the edge itself stays (its
# existence is still read until the read-path retirement) with an
# audit stamp of when and how much was migrated off it.
_CLEAR_EDGE: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {release_id}}})
      -[d:DEPLOYED_TO]->(e:Environment {{slug: {env_slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
SET d.deployments = NULL,
    d.migrated_at = {now},
    d.migrated_entries = {count}
RETURN e.slug AS slug
"""

# The variant for an edge with entries the migration could not
# validate: they are stashed on the edge (nothing reads the property)
# rather than destroyed with the array, so a hand repair stays
# possible.
_CLEAR_EDGE_WITH_SKIPPED: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {release_id}}})
      -[d:DEPLOYED_TO]->(e:Environment {{slug: {env_slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
SET d.deployments = NULL,
    d.migration_skipped = {skipped},
    d.migrated_at = {now},
    d.migrated_entries = {count}
RETURN e.slug AS slug
"""


def _iso(value: datetime.datetime) -> str:
    return deployment_nodes.as_utc(value).isoformat()


def _entry_node_id(project_id: str, entry: _ArrayEntry) -> str:
    """Deterministic node id for an entry with no run id.

    Derived from everything that distinguishes the entry -- release,
    environment, timestamp, and status -- so re-running the migration
    converges on the same node.
    """
    digest = hashlib.sha256(
        '|'.join(
            [
                project_id,
                entry.release_id,
                entry.env_slug,
                _iso(entry.event.timestamp),
                entry.event.status,
            ]
        ).encode()
    ).hexdigest()
    return f'mig{digest[:24]}'


def _history(entries: list[_ArrayEntry]) -> list[dict[str, str]]:
    """Status transitions, collapsing consecutive repeats.

    Matches the node writers' semantics: ``history`` records status
    *changes*, so a replayed webhook that re-reported the same status
    never appended.
    """
    transitions: list[dict[str, str]] = []
    for entry in entries:
        if transitions and transitions[-1]['status'] == entry.event.status:
            continue
        transitions.append(
            {
                'status': entry.event.status,
                'timestamp': _iso(entry.event.timestamp),
                'source': MIGRATION_SOURCE,
            }
        )
    return transitions


def _last_value(
    entries: list[_ArrayEntry],
    getter: abc.Callable[[models.DeploymentEvent], str | None],
) -> str | None:
    for entry in reversed(entries):
        value = getter(entry.event)
        if value:
            return value
    return None


class _EdgeRecord(typing.NamedTuple):
    """One migratable ``DEPLOYED_TO`` edge and what its array held."""

    release_id: str
    env_slug: str
    org_slug: str
    entry_count: int
    #: Raw items that failed ``DeploymentEvent`` validation (or were
    #: not entry objects at all).  Stashed on the edge at clear time so
    #: nothing the migration cannot represent is destroyed.
    skipped: list[typing.Any]


def _split_entries(
    raw: object,
) -> tuple[list[models.DeploymentEvent], list[typing.Any]]:
    """Split an edge's array into validated events and everything else.

    The "everything else" list is preserved verbatim: an entry the
    model cannot validate still described a real deployment once, and
    clearing the array must not be the moment it ceases to exist.
    """
    value = graph.parse_agtype(raw)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [], [value]
    if not isinstance(value, list):
        return [], [] if value in (None, '') else [value]
    events: list[models.DeploymentEvent] = []
    skipped: list[typing.Any] = []
    items = typing.cast('list[object]', value)
    for item in items:
        if not isinstance(item, dict):
            skipped.append(item)
            continue
        try:
            events.append(models.DeploymentEvent.model_validate(item))
        except ValueError:
            skipped.append(item)
    return events, skipped


def _collect_entries(
    rows: list[dict[str, typing.Any]],
) -> tuple[list[_EdgeRecord], list[_ArrayEntry], int]:
    """Parse the migratable edges into validated entries.

    Returns the edges (with anything they held that failed
    validation), the validated entries with their edge context, and
    how many raw items failed validation in total.
    """
    edges: list[_EdgeRecord] = []
    entries: list[_ArrayEntry] = []
    malformed = 0
    for row in rows:
        release_id = graph.parse_agtype(row.get('release_id'))
        env_slug = graph.parse_agtype(row.get('env_slug'))
        org_slug = graph.parse_agtype(row.get('org_slug'))
        if not (
            isinstance(release_id, str)
            and isinstance(env_slug, str)
            and isinstance(org_slug, str)
        ):
            continue
        tag = graph.parse_agtype(row.get('tag'))
        committish = graph.parse_agtype(row.get('committish'))
        events, skipped = _split_entries(row.get('deployments'))
        malformed += len(skipped)
        edges.append(
            _EdgeRecord(
                release_id=release_id,
                env_slug=env_slug,
                org_slug=org_slug,
                entry_count=len(events) + len(skipped),
                skipped=skipped,
            )
        )
        entries.extend(
            _ArrayEntry(
                event=event,
                release_id=release_id,
                release_tag=str(tag) if tag else None,
                release_committish=str(committish) if committish else None,
                env_slug=env_slug,
                org_slug=org_slug,
            )
            for event in events
        )
    return edges, entries, malformed


async def _existing_run_ids(
    db: graph.Graph, project_id: str, run_ids: list[str]
) -> set[str]:
    if not run_ids:
        return set()
    rows = await db.execute(
        _EXISTING_RUN_NODES,
        {'project_id': project_id, 'run_ids': run_ids},
        ['run_id'],
    )
    return {
        str(value)
        for value in (graph.parse_agtype(row.get('run_id')) for row in rows)
        if value
    }


async def migrate_deployment_arrays(
    db: graph.Graph,
    project_id: str,
    *,
    dry_run: bool = False,
) -> MigrationSummary:
    """Unnest one project's legacy deployment arrays into nodes.

    Entries sharing an ``external_run_id`` -- across every edge of the
    project, which is what resolves the duplicate-Release cross-links
    -- collapse into one node whose ``history`` keeps every transition
    and whose status is the newest entry's.  A node that already
    exists for the run id (a live writer recorded the rollout across
    the cutover) is left authoritative and only gains what it never
    had.  Entries without a run id become one node each, under a
    deterministic id so re-runs converge instead of duplicating.

    Each migrated edge's array is then cleared (``deployments`` set to
    ``NULL`` with a ``migrated_at`` stamp), which is both what makes
    the union read paths not double-count and what makes a re-run find
    nothing.  With *dry_run* set nothing is written and the summary
    reports the plan.
    """
    rows = await db.execute(
        _MIGRATABLE_EDGES,
        {'project_id': project_id},
        [
            'release_id',
            'tag',
            'committish',
            'env_slug',
            'org_slug',
            'deployments',
        ],
    )
    edges, entries, malformed = _collect_entries(rows)
    if not edges:
        return MigrationSummary()
    if malformed:
        LOGGER.warning(
            'deployment-migration: project %s has %d malformed array '
            'entr%s; not migrated, preserved on the edge as '
            'migration_skipped',
            project_id,
            malformed,
            'y' if malformed == 1 else 'ies',
        )

    by_run: dict[str, list[_ArrayEntry]] = {}
    runless: list[_ArrayEntry] = []
    for entry in entries:
        if entry.event.external_run_id:
            by_run.setdefault(entry.event.external_run_id, []).append(entry)
        else:
            runless.append(entry)
    for group in by_run.values():
        group.sort(key=lambda e: deployment_nodes.as_utc(e.event.timestamp))

    existing = await _existing_run_ids(db, project_id, sorted(by_run))

    created = 0
    if dry_run:
        # Identical run-less entries hash to one deterministic id, so
        # count distinct ids -- what a real run would create.
        runless_ids = {_entry_node_id(project_id, e) for e in runless}
        created = len(by_run) - len(existing) + len(runless_ids)
        LOGGER.info(
            'deployment-migration dry run: project %s: %d edge(s), %d '
            'entr%s -> %d run-id node(s) (%d already exist), %d '
            'run-less node(s), %d malformed skipped',
            project_id,
            len(edges),
            len(entries),
            'y' if len(entries) == 1 else 'ies',
            len(by_run),
            len(existing),
            len(runless),
            malformed,
        )
        return MigrationSummary(
            edges=len(edges),
            entries=len(entries),
            malformed=malformed,
            created=created,
            existing=len(existing),
            cleared_edges=0,
        )

    for run_id in sorted(by_run):
        group = by_run[run_id]
        last = group[-1]
        result = await db.execute(
            _MIGRATE_RUN_NODE,
            {
                'project_id': project_id,
                'external_run_id': run_id,
                'id': nanoid.generate(),
                'source': MIGRATION_SOURCE,
                'first_ts': _iso(group[0].event.timestamp),
                'last_ts': _iso(last.event.timestamp),
                'status': last.event.status,
                'note': last.event.note,
                'external_run_url': _last_value(
                    group, lambda e: e.external_run_url
                ),
                'performed_by': _last_value(group, lambda e: e.performed_by),
                'release_tag': last.release_tag,
                'release_committish': last.release_committish,
                'history': _history(group),
            },
            ['id', 'prior_created'],
        )
        if not result:
            continue
        node_id = str(graph.parse_agtype(result[0].get('id')))
        if graph.parse_agtype(result[0].get('prior_created')) is None:
            created += 1
        await db.execute(
            _ATTACH_IF_UNTARGETED,
            {
                'project_id': project_id,
                'deployment_id': node_id,
                'env_slug': last.env_slug,
                'org_slug': last.org_slug,
                'release_id': last.release_id,
            },
            ['id'],
        )
    for entry in runless:
        result = await db.execute(
            _MIGRATE_ENTRY_NODE,
            {
                'project_id': project_id,
                'id': _entry_node_id(project_id, entry),
                'env_slug': entry.env_slug,
                'org_slug': entry.org_slug,
                'release_id': entry.release_id,
                'source': MIGRATION_SOURCE,
                'timestamp': _iso(entry.event.timestamp),
                'status': entry.event.status,
                'note': entry.event.note,
                'external_run_url': entry.event.external_run_url,
                'performed_by': entry.event.performed_by,
                'release_tag': entry.release_tag,
                'release_committish': entry.release_committish,
                'history': _history([entry]),
            },
            ['id', 'prior_created'],
        )
        if result:
            prior = graph.parse_agtype(result[0].get('prior_created'))
            if prior is None:
                created += 1

    cleared = 0
    now = datetime.datetime.now(datetime.UTC).isoformat()
    for edge in edges:
        params: dict[str, typing.Any] = {
            'project_id': project_id,
            'release_id': edge.release_id,
            'env_slug': edge.env_slug,
            'org_slug': edge.org_slug,
            'now': now,
            'count': edge.entry_count,
        }
        query = _CLEAR_EDGE
        if edge.skipped:
            query = _CLEAR_EDGE_WITH_SKIPPED
            params['skipped'] = json.dumps(edge.skipped, default=str)
        done = await db.execute(query, params, ['slug'])
        cleared += len(done)

    summary = MigrationSummary(
        edges=len(edges),
        entries=len(entries),
        malformed=malformed,
        created=created,
        existing=len(existing),
        cleared_edges=cleared,
    )
    LOGGER.info('deployment-migration: project %s %s', project_id, summary)
    return summary


# ---------------------------------------------------------------------------
# Orphan-Release purge
# ---------------------------------------------------------------------------


class OrphanSummary(typing.NamedTuple):
    """What one project's orphan-release check found (or removed)."""

    tagged: int = 0
    #: Tagged releases with no run id and no deployment history --
    #: the shape of a pre-#216 failed dispatch.
    candidates: int = 0
    #: Candidates the remote positively confirmed have no such tag.
    orphans: int = 0
    deleted: int = 0
    blockers_deleted: int = 0
    #: Candidates whose tag lookup failed; left alone.
    unresolved: int = 0


_TAGGED_RELEASE_USAGE: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.tag IS NOT NULL
OPTIONAL MATCH (r)-[dt:DEPLOYED_TO]->(:Environment)
WITH r, count(dt) AS edges
OPTIONAL MATCH (r)-[:HAS_DEPLOYMENT]->(dn:Deployment)
WITH r, edges, count(dn) AS nodes
RETURN r.id AS id, r.tag AS tag,
       r.workflow_run_id AS run_id,
       edges AS edges, nodes AS nodes
"""

_ORPHAN_BLOCKERS: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(:Release {{id: {release_id}}})
      -[:BLOCKED_BY]->(b:Blocker)
RETURN b.id AS id
"""

# The delete re-checks every orphan criterion so anything that gained
# a run id or a deployment between the read and the write survives,
# and RETURNs the id (aliased before the DELETE) so the caller knows
# whether the delete actually happened -- the blockers come off only
# then.
_DELETE_ORPHAN_RELEASE: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})
      -[:HAS_RELEASE]->(r:Release {{id: {release_id}}})
WHERE r.tag = {tag} AND COALESCE(r.workflow_run_id, '') = ''
OPTIONAL MATCH (r)-[dt:DEPLOYED_TO]->(:Environment)
WITH r, count(dt) AS edges
OPTIONAL MATCH (r)-[:HAS_DEPLOYMENT]->(dn:Deployment)
WITH r, edges, count(dn) AS nodes
WHERE edges = 0 AND nodes = 0
WITH r, r.id AS rid
DETACH DELETE r
RETURN rid
"""

# Deleting the release detaches its BLOCKED_BY edges; this removes the
# Blocker nodes it left behind, by the ids read before the delete.
_DELETE_DETACHED_BLOCKERS: typing.Final[typing.LiteralString] = """
MATCH (b:Blocker)
WHERE b.id IN {blocker_ids}
DETACH DELETE b
"""


class _OrphanCandidate(typing.NamedTuple):
    id: str
    tag: str


async def purge_orphan_releases(
    db: graph.Graph,
    project_id: str,
    *,
    org_slug: str,
    dry_run: bool = False,
) -> OrphanSummary | None:
    """Remove tagged Releases whose tag never existed on the remote.

    Leftovers of pre-#216 failed dispatches: a misconfigured workflow
    wrote the node, the dispatch failed, nothing cleaned up.  A
    candidate is a tagged node with no ``workflow_run_id`` and no
    deployment history (no ``DEPLOYED_TO`` edge, no ``Deployment``
    node); it is an orphan only when the remote *positively* answers
    that the tag does not exist -- the lookup probes the repository's
    ``HEAD`` first, so an unreachable repository (deleted, renamed,
    credentials revoked) skips the project rather than reading every
    tag as absent.

    Returns ``None`` when the project's integration cannot answer at
    all, so the operation records it as skipped.  Deleting a Release
    takes its ``Blocker`` nodes and every edge with it; the delete
    re-checks the orphan criteria so nothing that gained history since
    the read is lost.  With *dry_run* set nothing is deleted and the
    orphans are logged.
    """
    from imbi.api.endpoints import project_deployments

    rows = await db.execute(
        _TAGGED_RELEASE_USAGE,
        {'project_id': project_id},
        ['id', 'tag', 'run_id', 'edges', 'nodes'],
    )
    tagged = 0
    candidates: list[_OrphanCandidate] = []
    for row in rows:
        release_id = graph.parse_agtype(row.get('id'))
        tag = graph.parse_agtype(row.get('tag'))
        if not release_id or not tag:
            continue
        tagged += 1
        run_id = graph.parse_agtype(row.get('run_id'))
        edges = graph.parse_agtype(row.get('edges'))
        nodes = graph.parse_agtype(row.get('nodes'))
        if run_id or int(edges or 0) or int(nodes or 0):
            continue
        candidates.append(_OrphanCandidate(str(release_id), str(tag)))
    if not candidates:
        return OrphanSummary(tagged=tagged)

    resolved = await project_deployments.resolve_remote_tags(
        db,
        org_slug=org_slug,
        project_id=project_id,
        tags=sorted({candidate.tag for candidate in candidates}),
        probe=True,
    )
    if resolved is None:
        LOGGER.info(
            'orphan-release-check: project %s has no integration that '
            'can confirm tag absence; skipped',
            project_id,
        )
        return None

    orphans = deleted = blockers_deleted = unresolved = 0
    for candidate in candidates:
        answer = resolved.get(candidate.tag)
        if answer != 'absent':
            if answer == 'error':
                unresolved += 1
                LOGGER.warning(
                    'orphan-release-check: could not confirm tag %s on '
                    'project %s; leaving release %s alone',
                    candidate.tag,
                    project_id,
                    candidate.id,
                )
            continue
        orphans += 1
        blocker_rows = await db.execute(
            _ORPHAN_BLOCKERS,
            {'project_id': project_id, 'release_id': candidate.id},
            ['id'],
        )
        blocker_ids = [
            str(value)
            for value in (
                graph.parse_agtype(row.get('id')) for row in blocker_rows
            )
            if value
        ]
        if dry_run:
            LOGGER.info(
                'orphan-release-check dry run: project %s release %s '
                '(tag %s) is confirmed absent from the remote; would '
                'delete it and %d blocker(s)',
                project_id,
                candidate.id,
                candidate.tag,
                len(blocker_ids),
            )
            continue
        removed = await db.execute(
            _DELETE_ORPHAN_RELEASE,
            {
                'project_id': project_id,
                'release_id': candidate.id,
                'tag': candidate.tag,
            },
            ['rid'],
        )
        if not removed:
            # The re-check declined: the release gained a run id or a
            # deployment since the read.  Its blockers stay with it.
            LOGGER.info(
                'orphan-release-check: release %s (tag %s) on project '
                '%s gained history since the read; left alone',
                candidate.id,
                candidate.tag,
                project_id,
            )
            continue
        deleted += 1
        if blocker_ids:
            await db.execute(
                _DELETE_DETACHED_BLOCKERS,
                {'blocker_ids': blocker_ids},
                [],
            )
            blockers_deleted += len(blocker_ids)
        LOGGER.info(
            'orphan-release-check: deleted release %s (tag %s) on '
            'project %s; the remote confirmed the tag does not exist',
            candidate.id,
            candidate.tag,
            project_id,
        )

    summary = OrphanSummary(
        tagged=tagged,
        candidates=len(candidates),
        orphans=orphans,
        deleted=deleted,
        blockers_deleted=blockers_deleted,
        unresolved=unresolved,
    )
    LOGGER.info(
        'orphan-release-check%s: project %s %s',
        ' dry run' if dry_run else '',
        project_id,
        summary,
    )
    return summary
