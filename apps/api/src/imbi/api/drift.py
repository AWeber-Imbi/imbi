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
3. :func:`resync_verdicts` -- the ``commit-sync`` operation re-reads the
   whole ref for the commits it just recorded, skipping the ones already
   answered.  The one repair for a *lost* notes push: (1) only ever
   ingests its own range and :func:`backfill_verdicts` runs once per
   project, so after that marker is set nothing else reads a note again.

``Release.drift_detected`` is ``bool | null`` where ``null`` means "no
note seen yet" -- a real state, because CI pushes notes asynchronously
to a separate ref.  ``drift_checked_at`` records when something last
looked, so "never looked" and "looked, no note" stay distinguishable.

A note flipping a tagged Release to ``drift_detected=true`` files a
``type='drift'`` blocker; any verdict that is not ``true`` resolves it
again (see ``sync_drift_blocker`` in the deployments endpoint module).
"""

from __future__ import annotations

import collections.abc
import datetime
import json
import logging
import typing

import fastapi

from imbi.api.auth import principals
from imbi.common import clickhouse, graph
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


async def verdicts_by_sha(
    project_id: str, shas: collections.abc.Iterable[str]
) -> dict[str, bool]:
    """Latest verdict per commit for a bounded sha set, keyed by
    lowercase full sha.

    A missing key *is* the "no verdict" state, which readers fail closed
    on (an unanswered commit displays as drifted).  A ClickHouse failure
    logs and answers ``{}`` -- indistinguishable from "no verdicts", and
    therefore also fail-closed -- rather than taking the commit list that
    asked down with it.
    """
    wanted = sorted({sha.lower() for sha in shas if sha})
    if not wanted:
        return {}
    try:
        rows = await clickhouse.query(
            # Table name is a module constant; values are bound params.
            f'SELECT sha, drift_detected FROM {VERDICT_TABLE} FINAL '  # noqa: S608
            'WHERE project_id = {project_id:String} '
            'AND sha IN {shas:Array(String)}',
            {'project_id': project_id, 'shas': wanted},
        )
    except Exception:
        LOGGER.exception(
            'could not read drift verdicts for project %s', project_id
        )
        return {}
    return {str(row['sha']): bool(row['drift_detected']) for row in rows}


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

    A project whose notes ref does not exist yet is a complete, empty
    listing, so it is marked and not asked again -- the alternative is a
    Git Data call per note-less project on every sweep, and the webhook
    covers a ref created later from its first push onward.

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


#: Unanswered Releases with no backoff filter, for the caller that
#: already holds every answer the ref can give and so pays nothing per
#: release to apply them.  :data:`_UNANSWERED_RELEASES` is the version
#: for a caller that must ask the remote per release.
_UNANSWERED_RELEASES_ALL: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.drift_detected IS NULL
  AND COALESCE(r.committish, '') <> ''
RETURN r.id AS id, r.tag AS tag, r.committish AS committish
ORDER BY r.created_at DESC
LIMIT {limit}
"""

#: Ceiling on Releases one notes resync stamps.  Each stamp is a graph
#: write plus a blocker sync, so a project with thousands of unanswered
#: releases would otherwise turn a commit sync into a write storm.
#: Newest-first, because those are the releases anyone is looking at.
STAMP_LIMIT = 500


class ResyncResult(typing.NamedTuple):
    """What one notes resync read and applied."""

    #: Notes read from the ref this run; already-answered commits are
    #: skipped, so a project in steady state records zero.
    recorded: int
    #: Releases whose ``drift_detected`` this run filled in.
    stamped: int


async def known_verdicts(project_id: str) -> dict[str, bool] | None:
    """Every commit this project already holds a verdict for.

    Read before enumerating a notes ref, for two reasons.  Cost: the
    bodies already answered for need not be fetched again, and fetching
    one is a request per note.  Correctness: their rows are then not
    rewritten, and a rewrite would carry a newer ``recorded_at`` than a
    verdict a webhook landed in the meantime -- which, under
    ``ReplacingMergeTree(recorded_at)``, is how a stale snapshot beats a
    fresh push.

    ``None`` when the store could not answer.  A caller must then read
    every note rather than treat nothing as known: skipping on an
    unavailable verdict store would report the ref as ingested while
    ingesting none of it.
    """
    try:
        rows = await clickhouse.query(
            # Table name is a module constant; values are bound params.
            f'SELECT sha, drift_detected FROM {VERDICT_TABLE} FINAL '  # noqa: S608
            'WHERE project_id = {project_id:String}',
            {'project_id': project_id},
        )
    except Exception:
        LOGGER.exception(
            'could not read known drift verdicts for project %s', project_id
        )
        return None
    return {
        str(row['sha']).lower(): bool(row['drift_detected']) for row in rows
    }


async def resync_verdicts(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
) -> ResyncResult | None:
    """Re-read the notes ref and answer whatever it can answer.

    The repair path for the gap between the two ordinary writers.  A
    push webhook only ever ingests its own range, and
    :func:`backfill_verdicts` runs once per project and then stops -- so
    once that marker is set, a notes push whose webhook was never
    delivered is never read again.  Commit sync is exactly what gets
    reached for when commits went missing, and it was recovering them
    without their verdicts, which readers fail closed on and show as
    drift indefinitely.

    Cost is bounded by what is *missing* rather than by history: the ref
    is enumerated (a call or two) with every already-answered commit
    skipped, so a project in steady state pays only the enumeration.
    The verdicts then in hand -- freshly read and previously known
    alike -- answer any Release naming one of their commits, capped by
    :data:`STAMP_LIMIT`.

    A Release no verdict answers is left untouched rather than stamped
    "looked, no note".  That stamp is :func:`sweep_project`'s backoff,
    and spending it here would silence the sweep's own re-check for a
    day over a note this pass never asked the remote for.

    Returns ``None`` when nothing can answer -- no capability bound, or
    one without git notes.  Raises when the verdicts could not be
    stored, so a caller reports a ClickHouse outage as a failure rather
    than as "nothing to do".
    """
    from imbi.api.endpoints import project_deployments
    from imbi.api.plugins import call_with_timeout

    try:
        (
            handler,
            ctx,
            credentials,
        ) = await project_deployments.resolve_deployment_capability(
            db, org_slug=org_slug, project_id=project_id
        )
    except fastapi.HTTPException as exc:
        # Same non-failure contract as the sweep: 404 is no capability
        # bound, 400 a bound one that cannot answer.
        if exc.status_code in (400, 404):
            return None
        raise
    known = await known_verdicts(project_id)
    try:
        listing = await call_with_timeout(
            handler.list_commit_notes(
                ctx,
                credentials,
                namespace=NAMESPACE,
                skip_shas=list(known) if known else [],
            )
        )
    except NotImplementedError:
        return None
    verdicts = {
        sha: parse_note_verdict(body) for sha, body in listing.notes.items()
    }
    recorded = await record_verdicts(project_id, verdicts)
    if recorded is None:
        raise RuntimeError(
            f'could not store drift verdicts for project {project_id}'
        )
    # The ref has now been read end to end, which is the claim
    # :func:`backfill_verdicts` marks -- so mark it and spare that pass.
    # Only on a complete listing, for the same reason it is: a partial
    # pass recorded as finished leaves those commits permanently
    # unanswered, which the rule reads as "nothing to do".
    if listing.complete:
        await db.execute(
            _MARK_BACKFILLED,
            {
                'project_id': project_id,
                'now': datetime.datetime.now(datetime.UTC).isoformat(),
            },
            ['id'],
        )
    answers: dict[str, bool] = dict(known or {})
    answers.update(
        {
            sha.lower(): verdict.drift_detected
            for sha, verdict in verdicts.items()
            if verdict.drift_detected is not None
        }
    )
    stamped = await _stamp_releases_from(
        db, org_slug=org_slug, project_id=project_id, answers=answers
    )
    return ResyncResult(recorded=recorded, stamped=stamped)


async def _stamp_releases_from(
    db: graph.Graph,
    *,
    org_slug: str,
    project_id: str,
    answers: dict[str, bool],
) -> int:
    """Apply verdicts already in hand to unanswered Releases.

    A ``Release.committish`` is the abbreviated SHA, so the match is by
    prefix -- and only where exactly one full SHA carries that prefix.
    Two commits sharing seven characters is unlikely but not impossible
    in a long-lived repo, and stamping a release with another commit's
    verdict is worse than leaving it to the sweep, which resolves the
    committish through the remote.
    """
    if not answers:
        return 0
    by_prefix: dict[str, list[bool]] = {}
    for sha, verdict in answers.items():
        by_prefix.setdefault(sha[:7], []).append(verdict)
    rows = await db.execute(
        _UNANSWERED_RELEASES_ALL,
        {'project_id': project_id, 'limit': STAMP_LIMIT},
        ['id', 'tag', 'committish'],
    )
    stamped = 0
    for row in rows:
        committish = str(graph.parse_agtype(row['committish'])).lower()
        candidates = by_prefix.get(committish[:7], [])
        if len(candidates) != 1:
            if candidates:
                LOGGER.warning(
                    'drift resync left %s on project %s alone: %d notes '
                    'share that committish',
                    committish,
                    project_id,
                    len(candidates),
                )
            continue
        await _stamp_release(
            db,
            org_slug=org_slug,
            project_id=project_id,
            release_id=str(graph.parse_agtype(row['id'])),
            tag=graph.parse_agtype(row['tag']),
            committish=committish,
            value=candidates[0],
        )
        stamped += 1
    return stamped
