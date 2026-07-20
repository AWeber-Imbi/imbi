"""On-demand deployment resync as a background job.

Mirrors :mod:`imbi_api.commit_sync` / :mod:`imbi_api.pr_sync`: the
endpoint enqueues onto a Valkey stream and the consumer runs the
backfill via the deployment plugin, recording last-run state on the
``Project`` node for the UI to poll.
"""
