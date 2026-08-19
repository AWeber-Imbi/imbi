"""Backfill and reconcile SBoM component facts in ClickHouse.

Phase two of the SBoM component migration. Every SBoM PUT has published
its component set to both stores since phase one, so what remains is the
releases ingested before that: their usage facts exist only as
``USES_COMPONENT_RELEASE`` edges in the graph.

Two entry points, both driven per project by the maintenance operations
in :mod:`imbi.api.maintenance.operations`:

- :func:`backfill_project` publishes a ``backfill`` batch for every
  release of a project that has no batch yet.
- :func:`reconcile_project` compares the two stores and reports the
  releases that disagree, writing nothing.

Chunking by project is not cosmetic. Reading the edge label as a whole
is what exhausts Postgres shared memory -- counting
``USES_COMPONENT_RELEASE`` fails outright with ``could not resize shared
memory segment``. Anchoring on one project's releases keeps every read
on the cheap outgoing direction.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import logging
import typing

import nanoid

from imbi.api import sbom
from imbi.common import clickhouse, graph, models

LOGGER = logging.getLogger(__name__)

#: Components of one project's releases, from the edges the backfill
#: exists to replace. Anchored on the project and followed outward, so
#: it never touches the fan-in that makes the reports unusable.
_PROJECT_RELEASE_COMPONENTS: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
      -[e:USES_COMPONENT_RELEASE]->(cr:ComponentRelease)
MATCH (c:Component)-[:HAS_RELEASE]->(cr)
RETURN r.id AS release_id,
       c.id AS component_id,
       c.purl_name AS purl_name,
       c.ecosystem AS ecosystem,
       cr.id AS component_release_id,
       cr.version AS version,
       e.scope AS scope,
       e.groups AS groups
"""


@dataclasses.dataclass(frozen=True, slots=True)
class BackfillSummary:
    """What one project's backfill published."""

    releases_published: int = 0
    releases_skipped: int = 0
    components_written: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class ReconcileSummary:
    """Where one project's two stores disagree.

    ``mismatched`` holds ``release_id -> reason`` and is what the
    operation logs. ``matched`` is carried so a run that finds nothing
    can say how much it actually checked, rather than being
    indistinguishable from a run that checked nothing.
    """

    matched: int = 0
    mismatched: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.mismatched


def _fingerprint(rows: typing.Iterable[tuple[str, str, str]]) -> str:
    """Hash a release's component set, order-independently.

    Row counts are a weak comparison: two stores can hold the same
    number of components while disagreeing about which, which is
    exactly the failure a backfill can introduce. Sorting before
    hashing makes the digest depend on content alone, so neither
    store's natural ordering enters into it.
    """
    digest = hashlib.sha256()
    for row in sorted(rows):
        digest.update('\\x1f'.join(row).encode())
        digest.update(b'\\x1e')
    return digest.hexdigest()


def _graph_components(
    rows: list[dict[str, typing.Any]],
) -> dict[str, list[dict[str, typing.Any]]]:
    """Group the graph rows by release, parsing agtype once."""
    by_release: dict[str, list[dict[str, typing.Any]]] = {}
    for row in rows:
        release_id = graph.parse_agtype(row.get('release_id'))
        if not release_id:
            continue
        by_release.setdefault(str(release_id), []).append(
            {key: graph.parse_agtype(value) for key, value in row.items()}
        )
    return by_release


async def _released_batches(project_id: str) -> set[str]:
    """Release ids that already have a batch, of any source.

    Used to skip work, never for correctness. A release that acquires
    an ingest batch between this read and the publish below is still
    resolved correctly, because ``source`` leads the reader's sort key
    and an ingest outranks a backfill in either landing order.
    """
    rows = await clickhouse.query(
        'SELECT DISTINCT release_id FROM imbi.release_component_batches'
        ' WHERE project_id = {project_id:String}',
        {'project_id': project_id},
    )
    return {str(row['release_id']) for row in rows}


async def _current_components(
    project_id: str,
) -> dict[str, list[tuple[str, str, str]]]:
    """One project's currently-published component set, per release.

    Resolves each release to a single batch first, then reads only that
    batch's rows -- the same two-step every report uses, so a
    reconciliation disagreement means the stores disagree rather than
    the reader having read differently.
    """
    rows = await clickhouse.query(
        'SELECT c.release_id AS release_id,'
        '       c.component_id AS component_id,'
        '       c.component_release_id AS component_release_id,'
        '       c.version AS version'
        '  FROM imbi.release_components AS c'
        ' INNER JOIN ('
        '   SELECT release_id,'
        "          argMax(batch_id, (source = 'ingest', recorded_at))"
        '            AS batch_id'
        '     FROM imbi.release_component_batches'
        '    WHERE project_id = {project_id:String}'
        '    GROUP BY release_id'
        ' ) AS b ON c.release_id = b.release_id AND c.batch_id = b.batch_id'
        ' WHERE c.project_id = {project_id:String}',
        {'project_id': project_id},
    )
    by_release: dict[str, list[tuple[str, str, str]]] = {}
    for row in rows:
        by_release.setdefault(str(row['release_id']), []).append(
            (
                str(row['component_id']),
                str(row['component_release_id']),
                str(row['version']),
            )
        )
    return by_release


async def backfill_project(
    db: graph.Graph, project_id: str
) -> BackfillSummary:
    """Publish a ``backfill`` batch per unbatched release of a project.

    Releases that already carry a batch are skipped, so a re-run costs
    one ClickHouse read per project and writes nothing. That skip is an
    optimisation, not a guard: correctness against a concurrent ingest
    comes from ``source`` leading the reader's sort key, not from this
    check, so there is no window between the read and the publish to
    lose.

    A release whose SBoM recorded no components is not represented in
    the graph edges at all, so it is indistinguishable here from one
    never ingested. Both are left alone rather than published as empty
    -- inventing an empty snapshot would assert the release has no
    dependencies, which is a stronger claim than "we have no record".
    """
    rows = await db.execute(
        _PROJECT_RELEASE_COMPONENTS,
        {'project_id': project_id},
        [
            'release_id',
            'component_id',
            'purl_name',
            'ecosystem',
            'component_release_id',
            'version',
            'scope',
            'groups',
        ],
    )
    by_release = _graph_components(rows)
    if not by_release:
        return BackfillSummary()

    already = await _released_batches(project_id)
    recorded_at = datetime.datetime.now(datetime.UTC)
    published = skipped = written = 0
    for release_id, components in by_release.items():
        if release_id in already:
            skipped += 1
            continue
        batch_id = nanoid.generate()
        records = [
            models.ReleaseComponentRecord(
                batch_id=batch_id,
                release_id=release_id,
                project_id=project_id,
                component_id=str(component['component_id']),
                component_release_id=str(component['component_release_id']),
                purl_name=str(component.get('purl_name') or ''),
                ecosystem=str(component.get('ecosystem') or ''),
                version=str(component.get('version') or ''),
                scope=str(component.get('scope') or ''),
                groups=_groups(component.get('groups')),
                recorded_at=recorded_at,
            )
            for component in components
        ]
        await sbom.publish_batch(
            project_id,
            release_id,
            batch_id,
            recorded_at,
            records,
            len(records),
            source='backfill',
        )
        published += 1
        written += len(records)
    return BackfillSummary(published, skipped, written)


def _groups(value: typing.Any) -> list[str]:
    """Coerce the edge's ``groups`` property to a list of strings.

    AGE stores list-of-string properties as JSON strings, and
    ``parse_agtype`` has already decoded whatever was there, so this
    sees a list on the happy path and something else on an old or
    hand-edited edge.
    """
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


async def reconcile_project(
    db: graph.Graph, project_id: str
) -> ReconcileSummary:
    """Compare a project's graph edges against its published batches.

    Compares content, not counts: each release's
    ``(component_id, component_release_id, version)`` set is sorted and
    hashed on both sides. Equal counts with different members is the
    failure mode a backfill can actually introduce, and a count check
    cannot see it.

    A release present in the graph with no published batch counts as a
    mismatch -- that is precisely what the backfill was supposed to fix,
    so the report has to notice when it did not.
    """
    rows = await db.execute(
        _PROJECT_RELEASE_COMPONENTS,
        {'project_id': project_id},
        [
            'release_id',
            'component_id',
            'purl_name',
            'ecosystem',
            'component_release_id',
            'version',
            'scope',
            'groups',
        ],
    )
    by_release = _graph_components(rows)
    published = await _current_components(project_id)

    matched = 0
    mismatched: dict[str, str] = {}
    for release_id, components in by_release.items():
        expected = _fingerprint(
            (
                str(component['component_id']),
                str(component['component_release_id']),
                str(component.get('version') or ''),
            )
            for component in components
        )
        if release_id not in published:
            mismatched[release_id] = (
                f'no published batch; graph has {len(components)} component(s)'
            )
            continue
        actual = _fingerprint(published[release_id])
        if actual == expected:
            matched += 1
        else:
            mismatched[release_id] = (
                f'component sets differ: graph {len(components)}, '
                f'clickhouse {len(published[release_id])}'
            )
    return ReconcileSummary(matched, mismatched)
