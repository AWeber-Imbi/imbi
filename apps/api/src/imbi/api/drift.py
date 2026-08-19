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
from imbi.common.plugins import errors as plugin_errors

LOGGER = logging.getLogger(__name__)

#: Notes namespace CI writes drift verdicts to (``refs/notes/<this>``).
NAMESPACE = 'imbi-drift'

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


def parse_note(body: str | None) -> bool | None:
    """Extract the drift verdict from one note body.

    Strict JSON, reading only the ``drift_detected`` key and ignoring
    unknown keys.  Anything else -- invalid JSON, a non-object, a
    non-boolean value -- logs a warning and answers ``None`` so a bad
    note never fails the webhook or the sweep.
    """
    if body is None:
        return None
    try:
        parsed: object = json.loads(body)
    except ValueError:
        LOGGER.warning('Ignoring invalid drift note: %.100r', body)
        return None
    if not isinstance(parsed, dict):
        LOGGER.warning('Ignoring non-object drift note: %.100r', body)
        return None
    value: object = typing.cast('dict[str, object]', parsed).get(
        'drift_detected'
    )
    if isinstance(value, bool):
        return value
    if value is not None:
        LOGGER.warning('Ignoring non-boolean drift_detected: %r', value)
    return None


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
    project's deployment plugin, then applies each changed note to the
    Releases on its annotated commit.  Raises
    :class:`NotImplementedError` when the plugin has no git-notes
    support, and lets plugin resolution's ``HTTPException`` propagate --
    the endpoint turns both into an honest status.
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
