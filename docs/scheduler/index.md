# Scheduler

`imbi-scheduler` triggers remote execution on a schedule. It runs on port 8005
and is served under `/scheduler` in the all-in-one image.

The scheduler **triggers**; it does not execute work. Every run is a single
synchronous HTTP call, and the outcome is recorded. Two target kinds cover the
platform:

| Target | Goes to | Runs as |
| --- | --- | --- |
| `api` | `imbi-api` | the scheduler's service account, or a delegated user |
| `gateway` | `imbi-gateway` | nothing — the endpoint has no bearer check and derives attribution from the payload |

Long-running work, agentic execution, and rule evaluation belong to whichever
service owns them. The scheduler pokes that service and records what came back.

## How a run happens

1. A trigger comes due. The claiming query
   (`FOR UPDATE SKIP LOCKED` over `scheduler.tasks`) guarantees exactly one
   replica fires it: concurrent replicas receive disjoint task sets, and the
   claiming transaction advances `next_run_at` before committing.
2. The task's identity is resolved *at fire time*, never at creation time. A
   `service_account` task uses the scheduler's own client credential; a
   `delegated_user` task exchanges that credential for a short-lived token
   scoped to the target user. `gateway` targets skip this step.
3. The target is rendered. `path`, `body`, `query`, and header values are Jinja2
   templates over `{now, task, run, last_run}`, matching the templating model
   `imbi-automations` uses so operators learn it once.
4. One HTTP call, bounded by the task's `timeout`, retried per its policy.
5. The result is classified and written to `imbi.scheduler_runs` in ClickHouse.

A failure to resolve identity is a `skipped` run, not a failed one, and it does
not consume retries — consent that has been revoked should stop a task quietly
rather than look like an outage.

## Stores

| Data | Where |
| --- | --- |
| Task definitions, trigger state | Postgres, schema `scheduler` |
| Run history | ClickHouse, `imbi.scheduler_runs` |
| Consent for delegated tasks | The graph, owned by `imbi-api`. The scheduler stores only a `consent_id` |

The scheduler stores no secrets. See
[ADR 0002](adr/0002-no-credential-store-in-v1.md).

## Relationship to `pg_cron`

Both are kept, deliberately. `pg_cron` is the system-level, in-database
operations tool; it runs SQL. `imbi-scheduler` is the user-level tool; it calls
endpoints and carries an identity. No overlap, no migration.

## Design decisions

- [ADR 0001: Trigger engine on psycopg3 rather than APScheduler](adr/0001-trigger-engine-on-psycopg.md)
- [ADR 0002: No encrypted credential store in v1](adr/0002-no-credential-store-in-v1.md)
- [ADR 0003: No local token-minting bridge](adr/0003-no-local-token-minting-bridge.md)

The `imbi-api` side of delegated execution is
[ADR 0016](../api/adr/0016-delegated-execution-for-scheduled-jobs.md).
