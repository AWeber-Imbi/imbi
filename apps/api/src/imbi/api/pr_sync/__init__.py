"""On-demand pull-request history sync for imbi-api.

A project-scoped "Sync Pull Requests" action enqueues a Valkey-stream
job; a background worker resolves the project's ``github-pr-sync``
webhook plugin, runs a full PR backfill via the plugin's service
credential, and records the last-sync status on the ``Project`` node for
the UI to poll.
"""

from imbi_api.pr_sync.queue import (
    consume_pr_sync,
    enqueue_pr_sync,
)
from imbi_api.pr_sync.service import (
    PRSyncStatus,
    PRSyncUnavailable,
    read_status,
    run_sync,
)

__all__ = [
    'PRSyncStatus',
    'PRSyncUnavailable',
    'consume_pr_sync',
    'enqueue_pr_sync',
    'read_status',
    'run_sync',
]
