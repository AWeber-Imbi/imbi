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
from imbi.api.maintenance import operations
from imbi.api.pr_sync import queue as pr_sync_queue
from imbi.common import graph

MaintenanceSlug = typing.Literal[
    'run-analysis',
    'remediate',
    'rescore',
    'deployment-resync',
    'deployment-sweep',
    'opslog-backfill',
    'release-repair',
    'blocker-migration',
    'commit-sync',
    'pr-sync',
    'search-reindex',
]


class OperationDefinition(typing.NamedTuple):
    """One global maintenance operation."""

    slug: MaintenanceSlug
    label: str
    description: str
    #: Rate-limit pause key honored before checkout, shared with the
    #: operation's stream consumers; ``None`` when not rate-limited.
    pause_key: str | None
    enumerate: abc.Callable[[graph.Graph], abc.Awaitable[list[str]]]
    execute: abc.Callable[
        [graph.Graph, valkey.Valkey, str],
        abc.Awaitable[operations.ExecuteOutcome],
    ]


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
                'known is attached to it. Projects without a deployment '
                'integration are skipped. Safe to re-run, and scheduled '
                'rather than only operator-triggered.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_deployment_sweep,
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
            slug='release-repair',
            label='Repair Release Identity',
            description=(
                'Fix releases the Deployments tab cannot recognize: '
                'normalize every release committish to the short form the '
                'deploy path looks up, move a tag onto the release that '
                'owns the deployment history for that commit, and drop the '
                'duplicates left behind. Only duplicates with no '
                'deployment history at all are removed; nothing else is '
                'deleted and no history, block state, or attribution is '
                'lost. Safe to re-run.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_release_repair,
        ),
        OperationDefinition(
            slug='blocker-migration',
            label='Migrate Release Blocks to Blockers',
            description=(
                'Convert releases still carrying the old blocked_at / '
                'blocked_reason flags into Blocker nodes, which is what '
                'deploys and promotes now check. A release left on the '
                'flags would read as shippable. Safe to re-run: migrated '
                'releases no longer carry the flags.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_blocker_migration,
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
        ),
    )
}
