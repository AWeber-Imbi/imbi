"""Restore deployments resync mislabelled as ``rolled_back``.

GitHub writes an ``inactive`` deployment status on a deployment when a
later one supersedes it.  Resync read the newest status of every
deployment it swept and mapped ``inactive`` straight to ``rolled_back``
-- and since every deployment except an environment's newest carries
one, that relabelled whole deployment histories.  ~14k nodes in the
production graph were in that state: about a quarter of every
``Deployment`` node, each asserting a rollback that never happened.

:meth:`GitHubDeploymentPlugin._latest_status` no longer does this, so
nothing new arrives broken.  The nodes already written stay wrong until
something repairs them, and a plain resync only reaches the deployments
inside the window it sweeps (one per environment by default), which is
a vanishing fraction of the affected set.

The repair needs no remote call.  ``upsert_deployment`` appends to
``history`` on every status change, so a node that was ``success``
before resync overwrote it still carries that ``success`` one entry
down.  This module reads the trail and puts back what was there.

Deliberately conservative:

* only ``rolled_back`` nodes are considered, and only those whose
  ``history`` actually records a prior ``success``.  A node whose
  history has no ``success`` -- the migration wrote ``rolled_back``
  directly, or the deployment really was superseded before reporting --
  is left alone.  There is no evidence to restore, and inventing one
  would be worse than the mislabel.
* ``updated_at`` is not touched.  It is the ordering key the
  current-release readers rank on, so bumping it to repair time would
  make every repaired node its environment's newest and hand the
  environment to whatever the repair happened to touch last.  The
  status is wrong; when it happened is not.

Runs as the ``deployment-status-repair`` maintenance operation.
"""

from __future__ import annotations

import datetime
import logging
import typing

from imbi.common import graph

LOGGER = logging.getLogger(__name__)

#: ``source`` recorded on the ``history`` entry this writes, so a
#: repaired node is distinguishable from one that reported ``success``
#: on its own.  Grepable on purpose.
REPAIR_SOURCE = 'status-repair'

#: Only nodes carrying this status are candidates.  Every ``rolled_back``
#: in the graph is derived from GitHub's ``inactive`` -- the gateway's
#: map (unreachable, no webhook is ever delivered for the state) and the
#: plugin's ``_to_event_status`` are its only producers -- so there is no
#: operator-initiated rollback for this to misread.
_MISLABELLED = 'rolled_back'

_RESTORED = 'success'


class RepairSummary(typing.NamedTuple):
    """What one project's repair did."""

    examined: int = 0
    repaired: int = 0
    #: ``rolled_back`` nodes whose history records no prior ``success``,
    #: so nothing could be restored.  Counted rather than ignored: it is
    #: how an operator tells "nothing to fix" from "could not fix".
    unrepairable: int = 0

    @property
    def wrote_anything(self) -> bool:
        return bool(self.repaired)


_CANDIDATES: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})<-[:BELONGS_TO]-(d:Deployment)
WHERE d.status = {status}
RETURN d.id AS id, d.history AS history, d.note AS note
"""

_REPAIR: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})<-[:BELONGS_TO]-(d:Deployment
      {{id: {deployment_id}}})
WHERE d.status = {status}
SET d.status = {restored},
    d.history = COALESCE(d.history, []) + [{{status: {restored},
         timestamp: {timestamp}, source: {source}}}]
RETURN d.id AS id
"""


def _restorable(history: object) -> bool:
    """Does this node's ``history`` record a ``success`` to put back?

    The trail is append-only, so the question is simply whether a
    ``success`` appears anywhere before the ``rolled_back`` that
    overwrote it.  Anywhere rather than immediately before: a
    deployment can pass through ``in_progress`` more than once when a
    watcher and a webhook both report it, and the entries between the
    success and the mislabel do not change what the success said.

    A malformed entry is skipped rather than raising -- the trail is
    plain JSON on the node and a single bad row must not stall a
    project's repair.
    """
    if not isinstance(history, list):
        return False
    # Cast rather than lean on the ``isinstance`` narrowing: it leaves
    # the element type unknown, which basedpyright rejects.  Casting to
    # ``list[typing.Any]`` instead would be the same type mypy already
    # inferred and it flags that as a redundant cast, so the two
    # checkers only agree on a cast that genuinely narrows.  Same shape
    # as the agtype decoding in ``imbi.common.deployments``.
    for entry in typing.cast('list[object]', history):
        if not isinstance(entry, dict):
            continue
        props = typing.cast('dict[str, typing.Any]', entry)
        if props.get('status') == _RESTORED:
            return True
    return False


async def repair_project(
    db: graph.Graph,
    project_id: str,
    *,
    now: datetime.datetime | None = None,
) -> RepairSummary:
    """Restore one project's mislabelled deployments.

    Idempotent: a repaired node no longer carries ``rolled_back``, so a
    second run does not see it.  The ``SET`` re-checks the status so a
    concurrent writer that legitimately moved the node between the read
    and the write is not clobbered.
    """
    ts = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    rows = await db.execute(
        _CANDIDATES,
        {'project_id': project_id, 'status': _MISLABELLED},
        ['id', 'history', 'note'],
    )
    examined = repaired = unrepairable = 0
    for row in rows:
        node_id = graph.parse_agtype(row.get('id'))
        if not isinstance(node_id, str):
            continue
        examined += 1
        if not _restorable(graph.parse_agtype(row.get('history'))):
            unrepairable += 1
            continue
        written = await db.execute(
            _REPAIR,
            {
                'project_id': project_id,
                'deployment_id': node_id,
                'status': _MISLABELLED,
                'restored': _RESTORED,
                'timestamp': ts.isoformat(),
                'source': REPAIR_SOURCE,
            },
            ['id'],
        )
        if written:
            repaired += 1
        else:
            # The node moved out of ``rolled_back`` between the read and
            # the write.  Someone else already answered for it, so this
            # is not a failure -- but it is not a repair either.
            LOGGER.debug(
                'deployment %s for project %s no longer mislabelled',
                node_id,
                project_id,
            )
    return RepairSummary(examined, repaired, unrepairable)
