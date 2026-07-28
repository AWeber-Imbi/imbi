# 1. Trigger engine on psycopg3 rather than APScheduler

Date: 2026-07-28

## Status

Accepted

Supersedes the engine choice in ADR 0016's referenced scheduler design, which
named APScheduler 4.x as the core.

## Context

The scheduler needs four trigger kinds (cron, interval, calendar, one-shot), a
guarantee that a given firing happens exactly once across replicas, and no
pickled job payloads. The design this service was specified from chose
APScheduler 4.x, using its shared relational data store to arbitrate single
firing and its `PostgresqlEventBroker` to wake replicas.

Checking that choice against the workspace as it stands at 2.19.0:

1. **APScheduler 4.x has not shipped.** The newest release is `4.0.0a6`,
   uploaded 2025-04-27 — an alpha, eighteen months old at the time of writing,
   declaring `requires_python>=3.9` and predating the Python 3.14 this
   workspace requires.
2. **It would introduce a second database stack.** Its relational data store
   requires `sqlalchemy[asyncio]>=2.0.24` and its Postgres event broker
   requires `asyncpg`. Every existing member speaks Postgres through
   `psycopg[binary,pool]` and the workspace contains no SQLAlchemy at all.
   Adopting it means two connection pools, two type-mapping layers, and two
   sets of failure modes in one process.
3. **It does not remove the work it appears to remove.** APScheduler owns DDL
   for *its* schedule and job tables only. Task definitions still need their
   own table — the design deliberately keeps no task payload in APScheduler,
   registering every schedule as `execute(task_id=...)` — and there is no
   relational-DDL mechanism in this repo to create that table either way. The
   only non-graph `CREATE TABLE` in the codebase is the hardcoded `embeddings`
   table in `imbi.common.graph.initializer`.

So the store layer has to be built regardless; the question is only whether
trigger arithmetic and firing arbitration come from an alpha dependency or from
this repo.

## Decision

Implement the trigger loop directly on psycopg3.

- **Task definitions and trigger state** live in a `scheduler` Postgres schema,
  created by a declarative `schemata.toml` plus an initializer that follows
  `imbi.common.graph.initializer`'s shape (psycopg3, `sql.Identifier`
  composition, `IF NOT EXISTS` throughout).
- **Single firing** comes from the claim query, not from a lock:

  ```sql
  SELECT … FROM scheduler.tasks
   WHERE enabled AND next_run_at <= %s
   ORDER BY next_run_at
     FOR UPDATE SKIP LOCKED
  ```

  Two replicas running this concurrently receive disjoint task sets. The
  claiming transaction advances `next_run_at` before committing, so a firing is
  consumed exactly once. This preserves the property the original design valued
  — no lease to hold, no dispatch-and-reconcile machinery, no Valkey — and it
  replaces the per-date `SETNX` lock `run_daily_tick` uses today for the same
  reason.
- **Waking** is `LISTEN`/`NOTIFY` on task mutation, plus a sleep bounded by the
  nearest `next_run_at`. A missed notification costs latency, not a missed run,
  because the bounded sleep re-polls.
- **Trigger arithmetic** lives in the trigger models themselves, each exposing
  `next_fire_time(after) -> datetime | None`. Cron uses `croniter`; interval,
  calendar, and one-shot are arithmetic over `datetime` in the task's IANA
  timezone.

## Consequences

### Positive

- No alpha dependency on the critical path, and no `sqlalchemy` + `asyncpg`
  addition to a psycopg3 workspace.
- The store follows the house pattern, so the `scheduler` schema is readable to
  anyone who has read `graph/initializer.py`.
- Single firing is a property of one SQL statement that a test can demonstrate
  directly, rather than of a dependency's internals.
- Nothing is pickled. Task definitions stay ordinary rows, API-mutable, and
  the trigger is data rather than code — which is what makes this decision
  reversible.

### Negative

- **Cron and DST arithmetic is now ours to get right.** This is the real cost.
  `croniter` covers expression parsing and stepping; the risk concentrates in
  timezone transitions. Mitigated by table-driven tests per trigger type that
  include a spring-forward and a fall-back boundary in a DST-observing zone,
  and by keeping resolution at one second (the design explicitly does not want
  sub-second precision).
- **Misfire handling, coalescing, and concurrency limits are ours too.** Two of
  the three are small: `misfire_grace_time` is a comparison against the claim
  timestamp, and coalescing falls out of claiming rather than needing a flag.
  `max_running_instances` was underestimated here — it was first built as an
  in-process counter, which silently bounds one replica rather than the task,
  and the deployment runs three. It is now a lease row in
  `scheduler.run_leases` taken under a per-task advisory lock, with an
  `expires_at` so a replica killed mid-run frees its own slot. The
  `asyncio.Semaphore` remains, but for what it can actually enforce: this
  process's ceiling on concurrent runs (`max_concurrent_runs`).
- If APScheduler 4 reaches a stable release and the platform later wants it,
  this is a swap of the engine module. The trigger models, task rows, target
  execution, and run history are untouched by that swap, so the decision stays
  reversible at roughly the cost of writing the adapter.

## Alternatives Considered

### APScheduler 4.0.0a6 behind a facade

Pin the exact alpha and isolate it behind a thin internal interface, which is
what the original design proposed as its own risk mitigation. **Rejected:** the
facade limits the blast radius of API churn but does nothing about the alpha
status itself, the two added dependencies, or the untested 3.14 support. Paying
those costs to avoid writing trigger arithmetic is a poor trade when the store
layer must be written either way.

### APScheduler 3.11.3

The stable line. **Rejected:** 3.x is sync-first, pickles job payloads into its
job store by default, and offers no shared-store single-firing guarantee — it
would need an external lock, which is precisely the mechanism this design set
out to remove.

### `pg_cron`

Already loaded in the Postgres image. **Rejected as the engine** for the reasons
ADR 0016 gives: it runs SQL, not HTTP calls, and cannot speak the auth flow.
`pg_cron` remains the system-level, in-database tool; this service is the
user-level one.
