# Scheduled Tasks

A task is four decisions: **when** it fires (`trigger`), **who** it fires as
(`identity`), **what** it calls (`target`), and **how** failures are handled
(`execution`).

## The API

Every route below is relative to `IMBI_SCHEDULER_API_PREFIX` (default `/api`).

| Method | Path | Permission |
| --- | --- | --- |
| `GET` | `/tasks` | `scheduled_task:read` |
| `POST` | `/tasks` | `scheduled_task:create` |
| `GET` | `/tasks/{slug}` | `scheduled_task:read` |
| `PATCH` | `/tasks/{slug}` | `scheduled_task:write` |
| `DELETE` | `/tasks/{slug}` | `scheduled_task:delete` |
| `POST` | `/tasks/{slug}/pause` | `scheduled_task:write` |
| `POST` | `/tasks/{slug}/resume` | `scheduled_task:write` |
| `POST` | `/tasks/{slug}/run` | `scheduled_task:run` |
| `POST` | `/tasks/{slug}/dry-run` | `scheduled_task:read` |
| `GET` | `/tasks/{slug}/runs` | `scheduled_task:read` |
| `GET` | `/runs/{run_id}` | `scheduled_task:read` |
| `POST` | `/runs/{run_id}/cancel` | `scheduled_task:run` |

Reading is unrestricted by ownership: seeing the schedule is not managing it, and
an operator asking why something fired needs to see the task that did it.
Changing a task requires either having created it or holding
`scheduled_task:admin`. A `kind: system` task needs `scheduled_task:admin`
however it was created — those are the platform's own jobs, and the scheduler's
service account is what creates them, so ownership alone would hand every system
task to that account's holders.

`PATCH` takes a JSON Patch. Server-owned fields (`/id`, `/created_by`, the
timestamps, `next_run_at`, and the outcome counters) are refused rather than
silently ignored, so a caller never believes an edit took effect.

## Triggers

| `kind` | Fields | Fires |
| --- | --- | --- |
| `cron` | `expression`, `jitter` | On a cron expression, in the task's timezone |
| `interval` | `seconds`, `minutes`, `hours`, `days`, `start_at`, `end_at` | Every fixed span |
| `calendar` | `days`, `weeks`, `months`, `at_time`, `start_at`, `end_at` | On calendar steps at a wall-clock time, DST included |
| `date` | `run_at` | Once |

`timezone` is an IANA name and applies to the whole task. `calendar` exists
because "the 1st of every month at 09:00" is not an interval — adding a month is
a calendar operation, and doing it in local time is what keeps it at 09:00 across
a DST boundary.

There is no `coalesce` option. One claim per due timestamp means a task that fell
behind fires once on catch-up rather than once per interval it missed, so
coalescing is not behavior to configure.

## Identity

| `kind` | Runs as | Requires |
| --- | --- | --- |
| `service_account` | The scheduler's own account | nothing further |
| `delegated_user` | `subject`, via a short-lived token | `consent_id` |

`delegated_user` is accepted and stored but does not execute yet: it needs the
token-exchange grant `imbi-api` has not implemented, so every firing is
`skipped` until then. See
[ADR 0003](adr/0003-no-local-token-minting-bridge.md).

Identity is resolved **at fire time**, never at creation time, so revoking
consent or deactivating a user stops future runs without touching the task. A
task that cannot resolve its principal records a `skipped` run — not a failure,
and it does not consume retries. Withdrawn consent should stop a task quietly
rather than look like an outage.

Consecutive skips are counted, and after `CONSECUTIVE_SKIPS_LIMIT` of them the
task is disabled: a task that can never resolve an identity is not going to fix
itself.

Only identity skips count toward that streak. A firing the engine declined for a
missed grace window or a full instance limit is also recorded as `skipped`, but
leaves both counters untouched — it says nothing about the task's identity, and
counting it would permanently disable a task whose only fault was a slow target
or a scheduler that was down.

## Targets

Only two, and neither takes an arbitrary URL — so every run is attributable by
construction. See [ADR 0002](adr/0002-no-credential-store-in-v1.md).

### `api`

Calls `imbi-api` as the task's identity.

```json
{
  "kind": "api",
  "method": "POST",
  "path": "/projects/{{ task.organization }}/refresh",
  "query": {},
  "body": null
}
```

`path` must be relative — an absolute URL is refused. A non-2xx response is a
`failed` run.

### `gateway`

Delivers a webhook payload to `imbi-gateway`. Carries no identity: that endpoint
has no bearer check and derives attribution from the payload, so a token would be
theater.

```json
{
  "kind": "gateway",
  "webhook_id": "nightly-scoring",
  "payload": {"event": "rescore"}
}
```

The gateway reports its disposition in the status code, and the run state follows
it: `202` is `succeeded`; `204` means the delivery was accepted and then dropped
(no matching webhook, no project resolved, no rule matched) and becomes
`no_effect`. Recording that as a success would hide a task that silently does
nothing forever. After `CONSECUTIVE_NO_EFFECT_LIMIT` of them the streak is
logged as a warning, but the task is left running: intermittent no-ops are
legitimate when the gateway's rules are conditional.

## Templating

`path`, `query` values, `body` values, header values, and `idempotency_key` are
Jinja2 templates over:

| Variable | Value |
| --- | --- |
| `now` | The firing time |
| `task` | The task, as JSON |
| `run` | `{id, fired_at}` |
| `last_run` | The previous `last_run_at`, ISO 8601, or `null` |

Same syntax as `imbi-automations`, so an operator learns it once. The
environment is sandboxed and undefined names are an error, not an empty string:
task definitions are writable by anyone holding `scheduled_task:create`, so they
are treated as untrusted input rather than as code. A template that fails to
render is a `failed` run and no request is made — a broken template is the
definition's fault, not the target's.

## Execution policy

| Field | Default | Meaning |
| --- | --- | --- |
| `timeout` | `120` | Seconds the HTTP call may take |
| `retries` | `0` | Attempts after the first |
| `retry_backoff` | `exponential` | `none`, `linear`, or `exponential` |
| `max_running_instances` | `1` | Concurrent runs of this task, across replicas |
| `misfire_grace_time` | `300` | Seconds late a firing may still run |
| `idempotency_key` | — | Template sent so the target can dedupe |

The two-minute default timeout is deliberate: a trigger endpoint is expected to
enqueue rather than block. Long-running work belongs to the service that owns it.

## Run states

| State | Meaning |
| --- | --- |
| `running` | In flight |
| `succeeded` | 2xx, or a gateway `202` |
| `no_effect` | Gateway `204` — accepted, then dropped |
| `failed` | Non-2xx, or the template would not render |
| `timed_out` | Exceeded `timeout` |
| `skipped` | No principal could be resolved, the misfire grace elapsed, the instance limit was full, or the task was deleted as it fired |
| `cancelled` | Cancelled through the API |

History lives in ClickHouse (`imbi.scheduler_runs`) and is read through
`GET /tasks/{slug}/runs` and `GET /runs/{run_id}`.

## Trying a task without firing it

`POST /tasks/{slug}/dry-run` renders the target and resolves the identity, then
reports what *would* be sent without sending it. Use it to check a template
before a schedule does it for you.

`POST /tasks/{slug}/run` fires immediately, subject to the same lease and
concurrency limit as a scheduled firing.

`POST /runs/{run_id}/cancel` interrupts a run in flight. The request is broadcast
with `pg_notify`, so it reaches whichever replica is holding the call open rather
than only the one that received it.
