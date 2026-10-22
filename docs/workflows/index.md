# Workflows Engine

`imbi-workflows` runs the workflow runs that imbi-api starts. It also keeps
the schedule and webhook triggers of active workflows in step with the
scheduler and the gateway. For how to build, activate, and run a workflow,
see [Workflows](../admin/workflows.md).

The engine runs on port 8006. It has no public API. Its only endpoint is
`GET /status`, which reports that the process is up and checks no
dependency.

## What each part owns

| Part | Owns |
|---|---|
| imbi-api | The Postgres schemas `workflows` and `workflow_runtime`. It starts runs, cancels them, and writes the trigger bindings |
| imbi-workflows | Runs the steps. Syncs the trigger bindings to the scheduler and the gateway |
| imbi-scheduler | Fires schedule triggers |
| imbi-gateway | Fires webhook triggers |

## The worker

Each process starts `IMBI_WORKFLOWS_WORKERS` workers (default `10`). Each
worker does these steps again and again:

1. It claims one run that is due.
2. It does one thing with the run: start it, close it, mark steps
   `skipped`, or make one call of one step.
3. It records the result and releases the run, with the time when the run
   is due next.

So the steps of one run run one at a time. Parallel branches run in turn.

A queued run starts only when no other run of the same workflow with the
same concurrency key is running, and no older run with that key is queued.
So runs with one key start in the order that imbi-api made them. A run with
a cancel request can always be claimed, so that it can close.

A worker that has nothing to do sleeps until the next run is due, or for
`IMBI_WORKFLOWS_POLL_INTERVAL` seconds, whichever is first. imbi-api sends a
Postgres `NOTIFY` when it starts or cancels a run, and that wakes the
workers at once. A lost `NOTIFY` costs latency, not a run.

## Leases

A claim takes the run with `FOR UPDATE SKIP LOCKED` and writes a lease in
`workflow_runtime.leases` in the same transaction. The lease lasts
`IMBI_WORKFLOWS_LEASE_SECONDS` (default `300`).

- Another worker cannot claim a run while its lease is valid.
- Each write of a claim checks the lease first. A worker whose lease expired
  and was taken by another worker writes nothing.
- One step call must end inside the lease. Keep it longer than the slowest
  step call.

So you can run more than one replica. On shutdown, a process waits up to 25
seconds for the calls in flight, then stops.

Deploy and agent steps do not hold a lease while they wait. The engine
checks a deployment every `IMBI_WORKFLOWS_DEPLOY_POLL_SECONDS` (default
`15`) and an agent task every `IMBI_WORKFLOWS_AGENT_POLL_SECONDS` (default
`30`).

For step failures, timeouts, and retries, see
[Failures, timeouts, and retries](../admin/workflows.md#failures-timeouts-and-retries).

## Run history

After each transaction that changes a run, the engine publishes the run and
its events to Iggy (`workflow_runs` and `workflow_run_events`). The sink
writes them to ClickHouse. When Iggy is not available, the engine still
runs. An archive sweep in imbi-api publishes the history later.

## The trigger reconciler

When a workflow activates, pauses, or is deleted, imbi-api writes the
trigger bindings that it wants to `workflows.trigger_bindings`, then sends a
`NOTIFY`. The reconciler then makes the scheduler and the gateway match:

| Binding | What the reconciler writes | On pause |
|---|---|---|
| Schedule | The scheduler task `workflow-<binding id>`. Its `api` target posts to the run endpoint as the `imbi-scheduler` service account | It disables the task |
| Webhook | A `gateway-actions#start_workflow` rule on the Webhook of the trigger | It keeps the rule. imbi-api refuses a run of a paused workflow with `409`, and the gateway records the delivery as no effect |

The reconciler records each binding as `synced`, or as `failed` with the
error. It also runs every `IMBI_WORKFLOWS_RECONCILE_INTERVAL` seconds
(default `300`), so it tries a failed binding again.

Do not edit the scheduler task or the gateway rule of a binding by hand. The
reconciler writes them again.

## Authentication

The engine calls imbi-api as the `imbi-workflows` service account, with a
client credential. It uses this account for deploy, rollback, and email
steps, and for the scheduler tasks of schedule triggers.

The seeded `imbi-workflows` role grants `project:read`,
`project:deployment:read`, `project:deployment:write`, and
`scheduled_task:read`, `:create`, `:write`, and `:delete`.

For deploy and rollback steps, an admin must also grant
`integration:act-as-service`. See
[Operator prerequisites](../admin/workflows.md#operator-prerequisites).

## Settings

The full list is in [Configuration](../api/configuration.md).

| Variable | Default | What it is |
|---|---|---|
| `IMBI_WORKFLOWS_SA_CLIENT_ID` | none | The client id of the `imbi-workflows` service account. Required |
| `IMBI_WORKFLOWS_SA_CLIENT_SECRET` | none | Its client secret. Required |
| `IMBI_INTERNAL_API_URL` | `http://localhost:8000` | Where the engine connects to imbi-api. Required when imbi-api runs in another container |
| `IMBI_API_URL` | none | The public URL of imbi-api. The engine uses its path, for example `/api`, as the route prefix. Required |
| `IMBI_WORKFLOWS_SCHEDULER_URL` | `http://localhost:8005/api` | The task API of imbi-scheduler, with its route prefix |
| `IMBI_WORKFLOWS_WORKERS` | `10` | Runs that one process works on at the same time |
| `IMBI_WORKFLOWS_POLL_INTERVAL` | `10` | The longest sleep between polls, in seconds |
| `IMBI_WORKFLOWS_LEASE_SECONDS` | `300` | How long a claim lasts. It must be more than 30 |
| `IMBI_WORKFLOWS_DEPLOY_POLL_SECONDS` | `15` | Seconds between checks of a deployment |
| `IMBI_WORKFLOWS_AGENT_POLL_SECONDS` | `30` | Seconds between checks of an agent task |
| `IMBI_WORKFLOWS_RECONCILE_INTERVAL` | `300` | Seconds between passes of the trigger reconciler |

The engine also needs `POSTGRES_URL`, `IMBI_AUTH_JWT_SECRET`, and
`IMBI_AUTH_ENCRYPTION_KEY`. The encryption key decrypts the AI provider
credentials for model decision steps. `IGGY_URL` is optional.

In the all-in-one image (`IMBI_SERVICE=all`), the entrypoint makes the
service account credential when both variables are not set. For the Helm
values, see [Helm values](../admin/workflows.md#helm-values).

To show the engine in the **System health** card of the Admin overview, set
`IMBI_INTERNAL_WORKFLOWS_URL` on imbi-api, for example
`http://imbi-workflows:8006`.
