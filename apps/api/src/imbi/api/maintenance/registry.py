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
    'opslog-backfill',
    'commit-sync',
    'pr-sync',
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
            slug='opslog-backfill',
            label='Backfill Deployments to Operations Log',
            description=(
                'Ensure operations_log has Deployed entries for every '
                'attributed deployment event on each release, so deployer '
                'attribution resolves for deployments recorded outside '
                'Imbi.'
            ),
            pause_key=None,
            enumerate=operations.enumerate_all_projects,
            execute=operations.execute_opslog_backfill,
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
    )
}
