"""Orphan-Release purge.

Find tagged ``Release`` nodes whose tag never came to exist on the
remote -- the shape a pre-#216 failed dispatch leaves behind -- and, in
purge mode, delete them along with their ``Blocker`` nodes.

The check is deliberately conservative: only a positive answer from the
remote that the tag does not exist marks a release an orphan.  A lookup
that fails leaves the release alone.
"""

from __future__ import annotations

import logging
import typing

from imbi.common import graph

LOGGER = logging.getLogger(__name__)


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
