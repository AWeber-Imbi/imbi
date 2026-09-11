"""Put back the push time commit re-syncs overwrote.

Every commit-sync path used to stamp ``commits.pushed_at`` with the
clock at ingest, and the table is a ``ReplacingMergeTree`` versioned on
``recorded_at`` -- so any re-sync of a commit already stored replaced
its row with a fresh ``pushed_at``.  Two producers did that at scale:

* the full backfill (``sync_all_history``, the ``commit-sync``
  maintenance operation), which stamps every commit a project has with
  the single instant the run started.  Three runs in August 2026 left
  roughly 19,000 commits across 600 projects sharing a handful of
  timestamps, their push order collapsed onto author order;
* the ``workflow_run`` webhook rule, which re-syncs a run's head commit
  when the run completes.  A release workflow runs against the commit
  a release was *cut from*, so that commit was re-stamped minutes after
  the release commit itself and sorted above it (#308).

``pushed_at`` orders the recent-commits feed, picks the commit-sync
gap-healing base, and picks the release-drift head, so the wrong values
mis-slice release ranges.  The sync no longer re-stamps a stored commit,
but nothing that reads GitHub can put the old values back: the commits
API carries author and committer dates, never a push time.

The ``events`` table can.  It holds every webhook delivery, and a
``push`` delivery names the commits it carried (``payload.commits[]``,
plus ``payload.after`` for the head) and the branch it was for
(``payload.ref``).  Its ``recorded_at`` is within about a second of the
``pushed_at`` the sync originally wrote from it.  So for each stored
commit, the earliest push delivery to the commit's own branch that
lists it is what its ``pushed_at`` was before anything overwrote it.

Deliberately conservative:

* only pushes to the branch the commit is stored under count.  A pull
  request's commits are also pushed to their feature branch, earlier,
  and the sync's branch-gated rule never recorded those -- matching
  them would order the commits by when their branch was pushed rather
  than by when they reached the default branch, which is a different
  wrong order.
* a row is rewritten only when its ``pushed_at`` is *later* than the
  delivery by more than :data:`TOLERANCE`.  Within tolerance it is the
  original stamp; earlier means an even earlier sync recorded it and
  that value is closer to the truth.
* a commit with no push delivery on record is left alone.  Deliveries
  only go back to June 2026, GitHub lists at most twenty commits per
  push payload, and a compare-healed gap has no delivery of its own.
  There is nothing to restore, and inventing a value would be worse
  than the collapsed one.

The rewrite is a re-insert of the full row with the corrected
``pushed_at`` and a fresh ``recorded_at`` -- the same read-modify-insert
``opslog-backfill`` uses -- so ``FINAL`` readers see it at once and the
background merge collapses the superseded version.  It also composes
with the sync's carry-forward, which reads the *earliest* ``pushed_at``
across row versions: the repaired value is the earlier one, so a
webhook re-sync racing the repair inherits it either way.

Runs as the ``commit-pushed-at-repair`` maintenance operation, with
``commit-pushed-at-check`` as its dry run.
"""

from __future__ import annotations

import datetime
import logging
import typing

import pydantic

from imbi.common import clickhouse, models

LOGGER = logging.getLogger(__name__)

#: How far a stored ``pushed_at`` may trail its push delivery before it
#: counts as re-stamped.  The webhook sync stamps ``now()`` while
#: handling the delivery, so the original value lands within a second
#: or two of ``events.recorded_at``; the smallest re-stamp -- a CI run
#: completing -- is minutes later.
TOLERANCE = datetime.timedelta(seconds=60)

_BRANCH_REF_PREFIX = 'refs/heads/'

#: Every column ``CommitRecord`` carries except ``recorded_at``, which
#: the re-insert regenerates.  Listed rather than ``SELECT *`` so a
#: column added to the table later is a loud failure here, not a row
#: silently rewritten with a default.
_COMMIT_COLUMNS: typing.Final = (
    'project_id',
    'sha',
    'short_sha',
    'ref',
    'message',
    'author_name',
    'author_email',
    'author_login',
    'author_user',
    'committer_name',
    'ci_status',
    'authored_at',
    'committed_at',
    'url',
    'pushed_at',
)

# ``payload`` is a JSON column; ``payload.commits[]`` is its array
# subcolumn and ``c.id`` the per-element path.  ``metadata.event_type``
# is the gateway's per-source label ('push'), distinct from the
# top-level ``type`` category ('webhook').
_DELIVERIES_SQL: typing.Final = (
    'SELECT recorded_at, '
    'toString(payload.ref) AS ref, '
    'toString(payload.after) AS after, '
    'arrayMap(c -> toString(c.id), payload.commits[]) AS commit_ids '
    'FROM events '
    'WHERE project_id = {project_id:String} '
    "AND type = 'webhook' "
    "AND toString(metadata.event_type) = 'push' "
    "AND toString(payload.ref) LIKE 'refs/heads/%'"
)

# Column list is a module constant; values are bound parameters.
_COMMITS_SQL: typing.Final = (
    'SELECT ' + ', '.join(_COMMIT_COLUMNS) + ' FROM commits FINAL '  # noqa: S608
    'WHERE project_id = {project_id:String} '
    'AND sha IN {shas:Array(String)}'
)


class RepairSummary(typing.NamedTuple):
    """What one project's repair did (or, dry run, would do)."""

    #: Push deliveries to a branch found for the project.
    deliveries: int = 0
    #: Stored commits a delivery to their own branch accounts for.
    examined: int = 0
    #: Rows rewritten -- or, on a dry run, rows that would be.
    repaired: int = 0
    #: Largest correction applied, in seconds.  Tells an operator
    #: whether a project's damage was the backfill (days) or a
    #: ``workflow_run`` re-stamp (minutes).
    largest_shift_seconds: int = 0


async def _push_times(
    project_id: str,
) -> tuple[int, dict[tuple[str, str], datetime.datetime]]:
    """Push deliveries read, and ``(branch, sha) -> earliest delivery``.

    A commit pushed to several branches (a feature branch, then the
    default branch on merge) gets one entry per branch, so the caller
    can pick the delivery for the branch the commit is stored under.
    """
    rows = await clickhouse.query(_DELIVERIES_SQL, {'project_id': project_id})
    earliest: dict[tuple[str, str], datetime.datetime] = {}
    for row in rows:
        recorded_at = clickhouse.as_utc_or_none(row.get('recorded_at'))
        ref = str(row.get('ref') or '')
        if recorded_at is None or not ref.startswith(_BRANCH_REF_PREFIX):
            continue
        branch = ref[len(_BRANCH_REF_PREFIX) :]
        listed = typing.cast('list[object]', row.get('commit_ids') or [])
        shas = {str(sha) for sha in listed if sha}
        # ``after`` is the head the delivery attests to even when the
        # payload's commit list is capped (GitHub sends at most twenty)
        # or empty (a branch created from an existing commit).
        after = str(row.get('after') or '')
        if after and after != '0' * 40:
            shas.add(after)
        for sha in shas:
            key = (branch, sha.lower())
            if key not in earliest or recorded_at < earliest[key]:
                earliest[key] = recorded_at
    return len(rows), earliest


def _repaired_record(
    row: dict[str, typing.Any], pushed_at: datetime.datetime
) -> models.CommitRecord:
    """The row as a ``CommitRecord`` carrying the restored push time.

    ``recorded_at`` is left to the model's default so the re-insert
    ranks newest under ``ReplacingMergeTree(recorded_at)``.
    """
    fields = {name: row.get(name) for name in _COMMIT_COLUMNS}
    fields['authored_at'] = clickhouse.as_utc_or_none(row.get('authored_at'))
    fields['committed_at'] = clickhouse.as_utc_or_none(row.get('committed_at'))
    fields['pushed_at'] = pushed_at
    return models.CommitRecord.model_validate(fields)


async def repair_project(
    project_id: str, *, dry_run: bool = False
) -> RepairSummary:
    """Restore one project's re-stamped commit push times.

    Idempotent: a repaired row sits within :data:`TOLERANCE` of its
    delivery, so a second run finds nothing to rewrite.
    """
    deliveries, push_times = await _push_times(project_id)
    if not push_times:
        return RepairSummary(deliveries=deliveries)
    shas = sorted({sha for _, sha in push_times})
    rows = await clickhouse.query(
        _COMMITS_SQL, {'project_id': project_id, 'shas': shas}
    )
    examined = 0
    largest = datetime.timedelta(0)
    repaired: list[pydantic.BaseModel] = []
    for row in rows:
        sha = str(row.get('sha') or '').lower()
        branch = str(row.get('ref') or '')
        delivered = push_times.get((branch, sha))
        if delivered is None:
            continue  # only pushed to some other branch; see module doc
        examined += 1
        stored = clickhouse.as_utc_or_none(row.get('pushed_at'))
        if stored is None:
            continue
        shift = stored - delivered
        if shift <= TOLERANCE:
            continue
        largest = max(largest, shift)
        repaired.append(_repaired_record(row, delivered))
    if repaired and not dry_run:
        await clickhouse.insert('commits', repaired)
        LOGGER.info(
            'restored pushed_at on %d commit(s) for project %s',
            len(repaired),
            project_id,
        )
    return RepairSummary(
        deliveries=deliveries,
        examined=examined,
        repaired=len(repaired),
        largest_shift_seconds=int(largest.total_seconds()),
    )
