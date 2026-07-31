# Configuration

`imbi-scheduler` reads its settings from the environment. Everything specific to
this service is prefixed `IMBI_SCHEDULER_`; the stores and the JWT secret are
shared with the rest of the platform and keep their platform-wide names.

## Required

| Variable | Purpose |
| --- | --- |
| `IMBI_AUTH_JWT_SECRET` | Verifies the bearer tokens presented to the API |
| `POSTGRES_URL` | Task definitions, trigger state, and the run leases |
| `CLICKHOUSE_URL` | Run history (`imbi.scheduler_runs`) |
| `IMBI_SCHEDULER_SA_CLIENT_ID` | The scheduler's own service-account client id |
| `IMBI_SCHEDULER_SA_CLIENT_SECRET` | Its client secret |
| `IMBI_API_URL` | imbi-api's **public** URL — see [Reaching imbi-api](#reaching-imbi-api) |
| `IMBI_INTERNAL_API_URL` | Where the scheduler **connects** to imbi-api — see [Reaching imbi-api](#reaching-imbi-api) |

Without the service-account credentials the service still starts and still
schedules, but no `api` target can resolve a principal, so every such firing is
recorded as `skipped`. The container entrypoint therefore refuses to start in
`scheduler` mode without them.

The account itself is seeded. `imbi-api setup` — or `imbi-api
setup-service-accounts` on an install that predates it — creates the
`imbi-scheduler` service account, gives it the seeded `imbi-scheduler` role, and
either adopts the credential these two variables name or generates one and
prints it once. Set them before running setup and they are what the account
authenticates with; leave them unset and setup tells you what to set them to.

In `all` mode the entrypoint provisions the pair itself when the environment does
not supply it, so a single-container deployment runs the scheduler with no
credential setup at all.

The seeded role grants `scheduled_task:*` plus every `:read` — enough to manage
the schedule and to inspect what a task reads, and deliberately not enough to
write anything else. A task whose `api` target *writes* needs that permission
added to the `imbi-scheduler` role first; until then it gets a 403.

## Reaching imbi-api

Two variables, deliberately distinct:

| Variable | What it is | Example |
| --- | --- | --- |
| `IMBI_INTERNAL_API_URL` | Where to *connect*. In-cluster, bare origin. | `http://imbi-api:8000` |
| `IMBI_API_URL` | imbi-api's *public* URL, whose path is the prefix it mounts its routes under. | `https://imbi.example.com/api` |

imbi-api mounts every router under the path component of its public URL, while
the internal URL is a bare origin. The scheduler joins the two: with the values
above it calls `http://imbi-api:8000/api/...`. Setting only the internal URL
means every request omits the prefix and 404s — including the token request,
whose 404 becomes an `IdentityError`, so every `api`-target firing is recorded
as `skipped` rather than failed. Both are required.

## Optional

| Variable | Default | Purpose |
| --- | --- | --- |
| `IMBI_SCHEDULER_API_PREFIX` | `/api` | Path the task and run routes are mounted under. `/status` is never prefixed. |
| `IMBI_SCHEDULER_SCHEMA` | `scheduler` | Postgres schema holding task definitions |
| `IMBI_SCHEDULER_GATEWAY_URL` | `http://localhost:8003` | imbi-gateway base URL for `gateway` targets |
| `IMBI_SCHEDULER_SA_SLUG` | `imbi-scheduler` | The service account's slug |
| `IMBI_SCHEDULER_MAX_CONCURRENT_RUNS` | `20` | Per-process ceiling on runs in flight |
| `IMBI_SCHEDULER_CONSECUTIVE_SKIPS_LIMIT` | `5` | Consecutive skipped runs before the task is disabled |
| `IMBI_SCHEDULER_CONSECUTIVE_NO_EFFECT_LIMIT` | `5` | Consecutive no-effect runs before a warning is logged |
| `IMBI_SCHEDULER_POLL_INTERVAL` | `30` | Upper bound in seconds on the engine's sleep |

`MAX_CONCURRENT_RUNS` is not bounded by the connection pool, and does not need
to be. The engine holds two of `POSTGRES_MAX_POOL_SIZE` (default 10) for the
life of the process — a `LISTEN` for task changes and another for cancels — but
a firing only takes a connection for short round trips and holds none across the
HTTP call, since neither the executor nor the identity resolver touches
Postgres. Twenty concurrent runs against eight free connections queue briefly on
checkout; capping the ceiling at the pool size would throttle throughput for
nothing.

`POLL_INTERVAL` is a ceiling, not a cadence. A change to the schedule arrives as
a `NOTIFY` and wakes the loop immediately; the interval only bounds how long a
*missed* notification can delay a firing. It costs latency, never a run.

### The prefix, and why it is a setting

The all-in-one image's Caddyfile mounts this service with `handle_path`, which
strips `/scheduler` before the request arrives, so a caller reaching
`/scheduler/api/tasks` hits `/api/tasks` here and the default is correct.

Under Okteto the endpoints pass the path through instead, so there the prefix
has to include it (`IMBI_SCHEDULER_API_PREFIX=/scheduler/api`). A relative value
is refused at startup rather than mounting the routes somewhere unreachable.

## Health

`/status` is unprefixed and stays that way, so a probe does not move when the
API is relocated. Both the container and the Helm chart read it directly on the
pod rather than through the reverse proxy.

## Running more than one replica

Safe, and the point of the design. A due firing is claimed with
`FOR UPDATE SKIP LOCKED`, so concurrent replicas receive disjoint task sets and
each occurrence is *claimed* by exactly one replica. That is a guarantee about
the claim, not about delivery: the claim commits before the outbound call, so a
replica lost in between drops the occurrence rather than duplicating it.
Execution is therefore at-most-once and best-effort — see
[ADR 0001](adr/0001-trigger-engine-on-psycopg.md). Per-task concurrency
(`execution.max_running_instances`) is enforced across replicas with a Postgres
advisory lock over a short-lived lease row.

Cancellation is broadcast with `pg_notify`, so cancelling a run reaches whichever
replica is holding the HTTP call open and interrupts it, not just the replica
that received the request.
