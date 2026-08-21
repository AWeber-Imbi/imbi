"""Registry of global maintenance operations.

The registry is the single source of truth for what the Maintenance
admin page offers: the ``GET /maintenance/operations`` endpoint renders
buttons from it, and the per-instance worker iterates it looking for
active runs. Adding an operation here is all that is required for it to
appear in the UI.
"""

from __future__ import annotations

import typing
from collections import abc

from valkey import asyncio as valkey

from imbi.api.commit_sync import queue as commit_sync_queue
from imbi.api.maintenance import log, operations
from imbi.api.pr_sync import queue as pr_sync_queue
from imbi.common import graph

MaintenanceSlug = typing.Literal[
    'run-analysis',
    'remediate',
    'rescore',
    'deployment-resync',
    'deployment-sweep',
    'deployment-status-repair',
    'opslog-backfill',
    'orphan-release-check',
    'orphan-release-purge',
    'commit-sync',
    'pr-sync',
    'search-reindex',
]


class ExecuteOperation(typing.Protocol):
    """The call signature every ``execute_*`` implements.

    A ``Callable[...]`` cannot express this: ``ctx`` is keyword-only, and
    a keyword-only parameter is not assignable to a positional slot, so
    every registry entry would fail the type check.

    The first three are positional-only. Implementations name the third
    for what they operate on -- ``project_id`` for all but
    ``search-reindex``, which takes an ``item_id`` -- and a protocol with
    named positional parameters would demand one spelling.
    """

    async def __call__(
        self,
        db: graph.Graph,
        client: valkey.Valkey,
        item_id: str,
        /,
        *,
        ctx: log.MaintenanceContext,
    ) -> operations.ExecuteOutcome: ...


class OperationDefinition(typing.NamedTuple):
    """One global maintenance operation."""

    slug: MaintenanceSlug
    label: str
    description: str
    #: Rate-limit pause key honored before checkout, shared with the
    #: operation's stream consumers; ``None`` when not rate-limited.
    pause_key: str | None
    enumerate: abc.Callable[[graph.Graph], abc.Awaitable[list[str]]]
    execute: ExecuteOperation
    #: Whether an enumerated work item *is* a project id, which decides
    #: whether the activity log can attribute a row to a project.
    #: ``search-reindex`` enumerates ``Label:node_id`` items instead.
    items_are_projects: bool = True


OPERATIONS: dict[MaintenanceSlug, OperationDefinition] = {
    definition.slug: definition
    for definition in (
        OperationDefinition(
            slug='run-analysis',
            label='Run Analysis',
            description=(
                'Run the Project Doctor analysis and persist a fresh '
                'report for every project.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_analysis,
        ),
        OperationDefinition(
            slug='remediate',
            label='Remediate Findings',
            description=(
                'Apply every fixable Project Doctor finding for every '
                'project, then refresh its report. Projects with no '
                'report or no fixable findings are skipped.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_remediate,
        ),
        OperationDefinition(
            slug='rescore',
            label='Recompute Scores',
            description=(
                'Enqueue a score recomputation for every project; the '
                'scoring workers process the queue. Completion means '
                'all projects were enqueued.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_rescore,
        ),
        OperationDefinition(
            slug='deployment-resync',
            label='Sync Deployments',
            description=(
                'Backfill recent remote deployments for every project '
                'with a deployment integration; projects without one '
                'are skipped.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_deployment_resync,
        ),
        OperationDefinition(
            slug='deployment-sweep',
            label='Close Out Stuck Deployments',
            description=(
                'Ask the remote what happened to every deployment still '
                'running after 30 minutes, and record the answer. '
                'Deployments nothing can resolve for a week are marked '
                'failed; a deployment recorded before its release was '
                'known is attached to it. Also backfills release drift '
                'verdicts from git notes for releases without an '
                'existing verdict. Projects without a deployment '
                'integration are skipped. Safe to re-run, and scheduled '
                'rather than only operator-triggered.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_deployment_sweep,
        ),
        OperationDefinition(
            slug='deployment-status-repair',
            label='Repair Deployments Mislabelled Rolled Back',
            description=(
                'Restore deployments that resync marked rolled back over '
                'a success. GitHub writes an inactive status on a '
                'deployment when a later one supersedes it, and resync '
                "read that as the outcome -- so most of a project's "
                'deployment history could end up claiming a rollback that '
                "never happened. Reads each node's own recorded history "
                'rather than the remote, so it makes no API calls and '
                'cannot be rate-limited. A node whose history holds no '
                'earlier success is left alone: there is nothing to '
                'restore. Does not change deployment timestamps, so it '
                'cannot move which release an environment reports. Safe '
                'to re-run.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_deployment_status_repair,
        ),
        OperationDefinition(
            slug='opslog-backfill',
            label='Backfill Deployments to Operations Log',
            description=(
                'Ensure the operations log has Deployed entries for every '
                'attributed deployment event on each release, so deployer '
                'attribution resolves for deployments recorded outside '
                'Imbi. Also fills the release committish in on existing '
                'entries that predate it, so release trains group across '
                'every environment.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_opslog_backfill,
        ),
        OperationDefinition(
            slug='orphan-release-check',
            label='Report Orphaned Releases (dry run)',
            description=(
                'Report releases whose tag never came to exist on the '
                'remote (leftovers of failed release dispatches) without '
                'deleting anything. Only counts a release when the '
                'remote positively confirms the tag is absent; projects '
                'whose integration cannot answer are skipped and logged.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_orphan_release_check,
        ),
        OperationDefinition(
            slug='orphan-release-purge',
            label='Delete Orphaned Releases',
            description=(
                'Delete releases whose tag never came to exist on the '
                'remote: tagged, never built, never deployed, and the '
                'remote positively confirms the tag is absent. Blockers '
                'attached to them are removed too. Run Report Orphaned '
                'Releases first and review the logs. Projects whose '
                'integration cannot answer are skipped.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_orphan_release_purge,
        ),
        OperationDefinition(
            slug='commit-sync',
            label='Sync Commits & Tags',
            description=(
                'Backfill full commit and tag history for every '
                'project with a commit-sync integration; projects '
                'without one are skipped.'
            ),
            pause_key=commit_sync_queue.PAUSE_KEY,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_commit_sync,
        ),
        OperationDefinition(
            slug='pr-sync',
            label='Sync Pull Requests',
            description=(
                'Backfill full pull-request history for every project '
                'with a PR-sync integration; projects without one are '
                'skipped.'
            ),
            pause_key=pr_sync_queue.PAUSE_KEY,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_pr_sync,
        ),
        OperationDefinition(
            slug='search-reindex',
            label='Reindex Search',
            description=(
                'Rebuild the vector search index for every searchable node '
                '-- documents, comments, releases, projects, and the rest '
                '-- from its current content. Run this after a bulk import '
                'or a change to the embedding model; ordinary saves index '
                'themselves.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_embeddable_nodes,
            execute=operations.execute_search_reindex,
            items_are_projects=False,
        ),
    )
}
