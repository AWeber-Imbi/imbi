"""Ingest CI drift verdicts written as git notes.

CI attaches a note per commit in the ``refs/notes/imbi-drift``
namespace, JSON like ``{"drift_detected": false}``.  Two writers feed
the ``Release`` node from it, matching the deployment-status pattern of
never relying on a webhook as the only writer:

1. :func:`apply_notes_diff` -- the gateway's ``update_release_drift``
   action posts the notes ref's ``before``/``after`` from a push event,
   and the plugin diffs the notes *tree* between them (the push's
   ``commits`` are commits of the notes ref, not the annotated
   commits).
2. :func:`sweep_project` -- the ``deployment-sweep`` maintenance
   operation backfills Releases whose ``drift_detected`` is still
   ``null``, covering webhook loss.

``Release.drift_detected`` is ``bool | null`` where ``null`` means "no
note seen yet" -- a real state, because CI pushes notes asynchronously
to a separate ref.  ``drift_checked_at`` records when something last
looked, so "never looked" and "looked, no note" stay distinguishable.

A note flipping a tagged Release to ``drift_detected=true`` files a
``type='drift'`` blocker; any verdict that is not ``true`` resolves it
again (see ``sync_drift_blocker`` in the deployments endpoint module).
"""

from __future__ import annotations

import datetime
import json
import logging
import typing

import fastapi

from imbi.api.auth import principals
from imbi.common import graph
from imbi.common.clickhouse import client as ch_client
from imbi.common.plugins import errors as plugin_errors

LOGGER = logging.getLogger(__name__)

#: Notes namespace CI writes drift verdicts to (``refs/notes/<this>``).
NAMESPACE = 'imbi-drift'

#: Per-commit verdict table.  The Release properties answer "did the
#: commit this tag points at drift"; this answers the same for *every*
#: commit, which is what OR-ing a range needs.
VERDICT_TABLE = 'commit_drift'

_VERDICT_COLUMNS = [
    'project_id',
    'sha',
    'drift_detected',
    'paths',
    'recorded_at',
]

REQUESTED_BY = principals.DRIFT_SYNC

#: How many unanswered Releases one sweep asks the remote about.  Every
#: answer is a few Git Data API calls, and the newest releases are the
#: ones whose notes are still expected to arrive.
SWEEP_LIMIT = 10

#: How long "looked, no note" holds before the sweep asks the remote
#: again.  Without this the sweep would re-ask about every note-less
#: release on every run, forever -- most projects have no drift notes
#: at all, and each ask is several Git Data API calls.
RECHECK_AFTER = datetime.timedelta(hours=24)

_SET_DRIFT: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->
      (r:Release {{id: {release_id}}})
SET r.drift_detected = {value},
    r.drift_checked_at = {now}
RETURN r.id AS id
"""

_RELEASES_FOR_COMMITTISH: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.committish = {committish}
RETURN r.id AS id, r.tag AS tag
"""

# Never-checked releases sort first (an absent ``drift_checked_at``
# coalesces to '', which orders before every ISO timestamp) so the
# :data:`SWEEP_LIMIT` slots cannot be monopolized by re-checks.
_UNANSWERED_RELEASES: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.drift_detected IS NULL
  AND COALESCE(r.committish, '') <> ''
  AND (r.drift_checked_at IS NULL OR r.drift_checked_at < {cutoff})
RETURN r.id AS id, r.tag AS tag, r.committish AS committish
ORDER BY COALESCE(r.drift_checked_at, '') ASC, r.created_at DESC
LIMIT {limit}
"""


class NoteVerdict(typing.NamedTuple):
    """One note's verdict and the paths that caused it.

    ``drift_detected`` is ``None`` for a note that gave no usable
    boolean.  ``paths`` explains a verdict but never implies one: it is
    empty when nothing drifted, and empty for every note CI writes today
    (``{"drift_detected": <bool>}`` and nothing else), even though
    ``drift`` itself reports ``drift_paths``.
    """

    drift_detected: bool | None
    paths: list[str]


def parse_note_verdict(body: str | None) -> NoteVerdict:
    """Extract the verdict and the drifting paths from one note body.

    Strict JSON, reading only ``drift_detected`` and ``drift_paths`` and
    ignoring unknown keys.  Anything else -- invalid JSON, a non-object,
    a non-boolean verdict -- logs a warning and answers a ``None``
    verdict so a bad note never fails the webhook or the sweep.
    """
    if body is None:
        return NoteVerdict(None, [])
    try:
        parsed: object = json.loads(body)
    except ValueError:
        LOGGER.warning('Ignoring invalid drift note: %.100r', body)
        return NoteVerdict(None, [])
    if not isinstance(parsed, dict):
        LOGGER.warning('Ignoring non-object drift note: %.100r', body)
        return NoteVerdict(None, [])
    note = typing.cast('dict[str, object]', parsed)
    value: object = note.get('drift_detected')
    if not isinstance(value, bool):
        if value is not None:
            LOGGER.warning('Ignoring non-boolean drift_detected: %r', value)
        return NoteVerdict(None, [])
    # Paths only ever accompany a ``true``: a range with nothing worth
    # acting on has no drifting paths by construction, so a ``false``
    # note carrying some is malformed and its paths mean nothing.
    if not value:
        return NoteVerdict(False, [])
    return NoteVerdict(True, _parse_paths(note.get('drift_paths')))


def _parse_paths(value: object) -> list[str]:
    """The note's ``drift_paths``, or ``[]`` when it has none usable.

    A malformed path list must not discard an otherwise good verdict --
    the paths only ever explain one.
    """
    if not isinstance(value, list):
        return []
    return [
        item
        for item in typing.cast('list[object]', value)
        if isinstance(item, str)
    ]


def parse_note(body: str | None) -> bool | None:
    """The verdict alone, for callers that do not need the paths."""
    return parse_note_verdict(body).drift_detected


async def record_verdicts(
    project_id: str, verdicts: dict[str, NoteVerdict]
) -> int | None:
    """Persist per-commit verdicts, one insert for the whole batch.

    Keyed by the annotated commit's full SHA to join ``imbi.commits``,
    so only callers holding full SHAs write here -- the notes tree is
    keyed that way, while a ``Release.committish`` is abbreviated and
    would collide.

    Notes with no usable verdict are skipped rather than written: a
    missing row *is* the "no verdict" state.

    Returns how many rows were written, or ``None`` when the write
    failed.  Zero and ``None`` have to stay distinguishable: a repo with
    no notes legitimately writes nothing, while a ClickHouse outage
    writes nothing and must not let a caller record the work as done.
    Failures are logged rather than raised -- the graph write has already
    succeeded, and the next push or backfill rewrites the rows.
    """
    now = datetime.datetime.now(datetime.UTC)
    rows = [
        [project_id, sha.lower(), verdict.drift_detected, verdict.paths, now]
        for sha, verdict in verdicts.items()
        if verdict.drift_detected is not None
    ]
    if not rows:
        return 0
    try:
        await ch_client.Clickhouse.get_instance().insert(
            VERDICT_TABLE, rows, _VERDICT_COLUMNS
        )
    except Exception:
        LOGGER.exception(
            'could not record %d drift verdicts for project %s',
            len(rows),
            project_id,
        )
        return None
    return len(rows)


async def _set_drift(
    db: graph.Graph, project_id: str, release_id: str, value: bool | None
) -> None:
    """Stamp the verdict and check time on one Release.

    ``SET`` to NULL removes a property in AGE, which is exactly the
    ``null`` state ``drift_detected`` needs -- so one query covers
    "note says true/false" and "looked, no note" alike.
    """
    await db.execute(
        _SET_DRIFT,
        {
            'project_id': project_id,
            'release_id': release_id,
            'value': value,
            'now': datetime.datetime.now(datetime.UTC).isoformat(),
        },
        ['id'],
    )


async def _stamp_release(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    release_id: str,
    tag: object,
    committish: str,
    value: bool | None,
) -> None:
    """Write one verdict: the Release fields, then the blocker tie-in."""
    from imbi.api.endpoints import project_deployments

    await _set_drift(db, project_id, release_id, value)
    if tag:
        await project_deployments.sync_drift_blocker(
            db,
            org_slug=org_slug,
            project_id=project_id,
            tag=str(tag),
            committish=committish,
            drift_detected=value,
            requested_by=REQUESTED_BY,
        )


async def apply_note(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    full_sha: str,
    body: str | None,
) -> int:
    """Apply one commit's note to every Release on that commit.

    Matches on the Release's own ``committish`` (the commit its tag
    points at) because the note describes that commit -- not an
    aggregate over the release range.  Returns how many Releases were
    stamped.
    """
    value = parse_note(body)
    committish = full_sha[:7].lower()
    rows = await db.execute(
        _RELEASES_FOR_COMMITTISH,
        {'project_id': project_id, 'committish': committish},
        ['id', 'tag'],
    )
    for row in rows:
        await _stamp_release(
            db,
            org_slug=org_slug,
            project_id=project_id,
            release_id=str(graph.parse_agtype(row['id'])),
            tag=graph.parse_agtype(row['tag']),
            committish=committish,
            value=value,
        )
    return len(rows)


async def apply_notes_diff(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    before: str,
    after: str,
) -> int:
    """Ingest one push to the notes ref.

    Diffs the notes tree between ``before`` and ``after`` through the
    project's deployment plugin, records every verdict against its
    commit, then applies each changed note to the Releases on its
    annotated commit.  Raises :class:`NotImplementedError` when the
    plugin has no git-notes support, and lets plugin resolution's
    ``HTTPException`` propagate -- the endpoint turns both into an
    honest status.

    A note the push *removed* arrives as a ``None`` body and leaves the
    recorded verdict in place.  Deliberate: CI removes a drift note only
    by rewriting the ref, and the alternative -- deleting the row -- would
    silently turn a range clean on a force push.
    """
    from imbi.api.endpoints import project_deployments
    from imbi.api.plugins import call_with_timeout

    (
        handler,
        ctx,
        credentials,
    ) = await project_deployments.resolve_deployment_capability(
        db, org_slug=org_slug, project_id=project_id
    )
    changed = await call_with_timeout(
        handler.diff_commit_notes(
            ctx,
            credentials,
            namespace=NAMESPACE,
            before=before,
            after=after,
        )
    )
    await record_verdicts(
        project_id,
        {sha: parse_note_verdict(body) for sha, body in changed.items()},
    )
    updated = 0
    for full_sha, body in changed.items():
        try:
            updated += await apply_note(
                db,
                org_slug=org_slug,
                project_id=project_id,
                full_sha=full_sha,
                body=body,
            )
        except Exception:
            # One bad note must not hold the rest of the push hostage:
            # the write is idempotent, so a retry would re-apply the
            # leading notes and still die on the same SHA forever.
            LOGGER.exception(
                'could not apply the note for %s on project %s',
                full_sha,
                project_id,
            )
    return updated


_BACKFILLED_AT: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
RETURN p.drift_verdicts_at AS at
"""

_MARK_BACKFILLED: typing.Final[typing.LiteralString] = """
MATCH (p:Project {{id: {project_id}}})
SET p.drift_verdicts_at = {now}
RETURN p.id AS id
"""


async def backfill_verdicts(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
) -> int | None:
    """Record every note in the namespace, once per project.

    The cover for notes written before Imbi read them.  Reading the whole
    notes tree costs one Git Data call per note body, so this runs once
    and then stops, guarded by ``Project.drift_verdicts_at``.

    That marker, rather than "does the table hold a row for this
    project": the webhook writes a row on the first push after deploy, so
    a row-count guard would declare the backfill done for exactly the
    active projects whose history most needs it, and their older notes
    would never be read.

    The marker is set only after a *complete* enumeration.  A listing
    that could not read every note leaves it unset so the next sweep
    tries again -- recording a partial pass as finished would leave those
    commits permanently unanswered, which the rule reads as "nothing to
    do".

    Returns how many verdicts were recorded, or ``None`` when nothing
    could answer -- no capability bound, or one without git notes.
    Raises when the verdicts could not be stored: the maintenance
    operation turns that into a failed item, where returning zero would
    have reported a ClickHouse outage as "nothing to do".
    """
    from imbi.api.endpoints import project_deployments
    from imbi.api.plugins import call_with_timeout

    marked = await db.execute(
        _BACKFILLED_AT, {'project_id': project_id}, ['at']
    )
    if marked and graph.parse_agtype(marked[0]['at']) is not None:
        return 0
    try:
        (
            handler,
            ctx,
            credentials,
        ) = await project_deployments.resolve_deployment_capability(
            db, org_slug=org_slug, project_id=project_id
        )
    except fastapi.HTTPException as exc:
        if exc.status_code in (400, 404):
            return None
        raise
    try:
        listing = await call_with_timeout(
            handler.list_commit_notes(ctx, credentials, namespace=NAMESPACE)
        )
    except NotImplementedError:
        return None
    recorded = await record_verdicts(
        project_id,
        {sha: parse_note_verdict(body) for sha, body in listing.notes.items()},
    )
    if recorded is None:
        # Raised rather than returned as zero: the caller cannot tell a
        # lost write from an empty ref, and reporting a ClickHouse
        # outage as "nothing to do" hides the one pass this project
        # gets.  The marker stays unset either way, so a later sweep
        # retries.
        raise RuntimeError(
            f'could not store drift verdicts for project {project_id}'
        )
    # Not ``recorded > 0``: a ref with no notes writes nothing and is
    # still finished, and gating on the count would re-read its tree on
    # every sweep forever.
    if listing.complete:
        await db.execute(
            _MARK_BACKFILLED,
            {
                'project_id': project_id,
                'now': datetime.datetime.now(datetime.UTC).isoformat(),
            },
            ['id'],
        )
    else:
        LOGGER.warning(
            'drift notes for project %s were incomplete; leaving the '
            'backfill unmarked so a later sweep retries',
            project_id,
        )
    return recorded


async def sweep_project(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    now: datetime.datetime | None = None,
) -> int | None:
    """Backfill drift for Releases no note has answered yet.

    Asks the plugin for the note on each unanswered Release's own
    committish (never-checked first, then newest) and stamps the
    verdict -- including "looked, no note", which sets
    ``drift_checked_at`` while ``drift_detected`` stays ``null``.
    That stamp is also the backoff: a release checked within
    :data:`RECHECK_AFTER` is not asked about again, so projects whose
    CI writes no notes are not re-polled on every sweep.
    Returns how many Releases were stamped, or ``None`` when the
    project has no plugin that can answer -- not a failure, just
    nothing to ask.  :class:`PluginRateLimited` propagates so the
    maintenance worker requeues the project instead of burning the
    remaining budget on a throttled remote.
    """
    from imbi.api.endpoints import project_deployments
    from imbi.api.plugins import call_with_timeout

    now = now or datetime.datetime.now(datetime.UTC)
    rows = await db.execute(
        _UNANSWERED_RELEASES,
        {
            'project_id': project_id,
            'limit': SWEEP_LIMIT,
            'cutoff': (now - RECHECK_AFTER).isoformat(),
        },
        ['id', 'tag', 'committish'],
    )
    if not rows:
        return 0
    try:
        (
            handler,
            ctx,
            credentials,
        ) = await project_deployments.resolve_deployment_capability(
            db, org_slug=org_slug, project_id=project_id
        )
    except fastapi.HTTPException as exc:
        # 404: no deployment capability bound; 400: the bound plugin
        # cannot answer.  Same non-failure contract as the deployment
        # sweeper.
        if exc.status_code in (400, 404):
            return None
        raise
    stamped = 0
    for row in rows:
        committish = str(graph.parse_agtype(row['committish']))
        try:
            body = await call_with_timeout(
                handler.get_commit_note(
                    ctx,
                    credentials,
                    namespace=NAMESPACE,
                    committish=committish,
                )
            )
        except NotImplementedError:
            return None
        except plugin_errors.PluginRateLimited:
            raise
        except Exception:
            LOGGER.exception(
                'drift sweep could not read the note for %s on project %s',
                committish,
                project_id,
            )
            continue
        await _stamp_release(
            db,
            org_slug=org_slug,
            project_id=project_id,
            release_id=str(graph.parse_agtype(row['id'])),
            tag=graph.parse_agtype(row['tag']),
            committish=committish,
            value=parse_note(body),
        )
        stamped += 1
    return stamped
