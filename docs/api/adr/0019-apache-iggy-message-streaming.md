# ADR 0019: Adopt Apache Iggy as the Message Streaming Service

Date: 2026-09-04

## Status

Proposed

## Context

Imbi has no durable message stream. Services talk to each other over
HTTP and to their stores directly, so anything that happens in one place
and matters somewhere else is either written straight into a database or
lost. Three kinds of work need a stream that persists messages, keeps
them ordered per topic, and lets consumers read at their own pace:

- **Analytics writes.** Rows for ClickHouse, produced by every service.
- **Notifications.** Events other Imbi services react to, such as a
  deployment finishing or a user being mentioned, fanned out to
  slackbot, email and whatever comes next.
- **Metrics.** Time-series facts for BI, such as project scores, drift
  counts and pull-request counts, recorded as they are observed rather
  than recomputed from the graph on demand.

[Apache Iggy](https://iggy.apache.org) is a persistent message streaming
server with streams, topics and partitions, server-side consumer-group
offsets, TCP, QUIC and HTTP transports, an official Python SDK, and a
connectors runtime with sink plugins including ClickHouse. It runs as a
single binary with local storage, which suits Imbi's deployment size
better than a Kafka cluster would.

This ADR adopts Iggy as that streaming service and decides its first use:
moving the ClickHouse writes onto it. The notification and metric streams
are named here only so the stream and topic conventions are set with them
in mind; each gets its own decision when it is built.

### First use: the ClickHouse write path

Every Imbi service writes analytics rows straight into ClickHouse through
`imbi.common.clickhouse`, and most call sites insert one row per request.
The survey below is the full list of write paths at the time of writing.

| Service / member | Call site                                                                           | Table                                                  | Batch today                            |
| ---------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------- |
| gateway          | `notifications.py` `DeliveryRecorder.record_received`                               | `events`                                               | one row per matched project, version 0 |
| gateway          | `notifications.py` `DeliveryRecorder.record_dispositions`                           | `events`                                               | same rows re-inserted with version 1   |
| api              | `plugins/lifecycle_dispatch.py`                                                     | `events`                                               | per dispatch                           |
| api              | `endpoints/_document_events.py`, `comments.py`, `projects.py`                       | `events`                                               | single row                             |
| api              | `endpoints/operations_log.py`, `project_configuration.py`, `project_deployments.py` | `operations_log`                                       | single row                             |
| api              | `maintenance/operations.py` (backfill)                                              | `operations_log`                                       | per project                            |
| api              | `maintenance/log.py`                                                                | `maintenance_log`                                      | buffered per item, `async_insert`      |
| api              | `endpoints/_document_history.py`                                                    | `document_versions`                                    | one or two rows                        |
| api              | `endpoints/_document_reads.py`                                                      | `document_read_events`, `document_read_sessions`       | per read / per sweep                   |
| api              | `drift.py`                                                                          | `commit_drift`                                         | per verdict batch                      |
| api              | `sbom.py`                                                                           | `release_components`, then `release_component_batches` | fact rows, then one batch row          |
| api              | `email/__init__.py`                                                                 | `email_audit`                                          | single row                             |
| common           | `scoring/history.py`                                                                | `score_history`                                        | single row                             |
| scheduler        | `runs.py` `record`                                                                  | `scheduler_runs`                                       | single row, several times per run      |
| github plugin    | `commits.py`, `pull_requests.py`                                                    | `commits`, `tags`, `pull_requests`, `commit_drift`     | per sync page / single row             |

Two engines are in use. `events`, `operations_log`, `pull_requests`,
`commits`, `commit_drift`, `document_versions`, `tags`, `scheduler_runs`,
`document_read_events` and `document_read_sessions` are
`ReplacingMergeTree`. `score_history`, `release_components`,
`release_component_batches` and `maintenance_log` are plain `MergeTree`.

Single-row inserts create one MergeTree part each. The maintenance log
already works around that with `async_insert`. Moving the writes onto
Iggy lets the ClickHouse sink batch them, decouples request latency from
ClickHouse availability, and gives us a replayable record of what each
service emitted. It is also the smallest useful way to put the streaming
service into production before the notification and metric streams
depend on it.

### Constraints found during evaluation

1. **The Python SDK has no prebuilt wheel for Python 3.14, but builds
   from source.** Every `apache-iggy` release through 0.9.0.dev6 ships
   wheels for CPython 3.10 to 3.13 only, matching the upstream wheel
   workflow. The sdist pins PyO3 0.29, which supports 3.14. Verified:
   `pip install --pre apache-iggy==0.9.0.dev6` inside `python:3.14-slim`
   with rustup installed compiles in about one minute on arm64 and the
   module imports on 3.14.7. Imbi's image build therefore needs a Rust
   toolchain in the Python builder stage, or a wheel built once in CI.
2. **Iggy also has a first-class HTTP API** (`IGGY_HTTP_ADDRESS`, `:3000`
   in the Docker image) with `POST /users/login` and
   `POST /streams/{stream}/topics/{topic}/messages`. It is the fallback
   if the SDK build ever becomes a problem; `httpx` is already a
   dependency of `imbi-common`.
3. **The ClickHouse sink plugin is not distributed as a binary.** The
   `apache/iggy-connect` image contains only the `iggy-connectors`
   runtime; upstream's publish config states that plugin `.so` files are
   not bundled. The edge release ships prebuilt plugin tarballs for eight
   connectors, and ClickHouse is not among them. The sink exists as
   source under `core/connectors/sinks/clickhouse_sink` with an
   integration test fixture.
4. **A sink configuration binds one stream and a static topic list to
   one table.** The runtime opens one consumer group per listed topic
   when the sink starts. There is no wildcard and no header-based table
   routing. The list is re-read only on a sink restart.
5. **Webhooks are created at runtime.** A topic per webhook would need
   the sink configuration regenerated and the sink restarted on every
   webhook create or delete. The event row already records
   `metadata.webhook_id` and `integration`, so per-webhook questions are
   answerable in ClickHouse without a per-webhook topic.
6. **Some code reads what it just wrote.**
   `operations_log.complete_opslog_entry` selects the open row by
   `external_run_id` and re-inserts it completed. The scheduler records a
   run and its endpoints serve it back. `sbom.py` inserts fact rows and
   then a batch row, and readers treat the batch row as the signal that
   the fact rows are complete.
7. **Delivery is at-least-once.** The sink retries failed inserts with
   backoff and has no deduplication token. A duplicate delivery collapses
   on a `ReplacingMergeTree` table but persists on a plain `MergeTree`
   table.

## Decision

### 1. Topology: a stream per subject, topics as the subject's own dimension

A stream is a subject with one row shape. Topics split that stream along
whatever dimension is useful for that subject; the dimension is chosen
per stream, not globally. Streams that land in ClickHouse map one stream
to one table, which is exactly the model the sink expects. Streams are
not limited to ClickHouse: the same bus will carry subjects with other
consumers, and the naming rule has to hold for those too.

The topic set of a stream is decided in code, not here. What matters for
the sink is that it is fixed at build time, so the sink configuration is
static and can be generated from one Python mapping. Examples of the
shape, including two streams this ADR does not implement:

| Stream                   | Topic dimension              | Example topics                            | Consumers                                               |
| ------------------------ | ---------------------------- | ----------------------------------------- | ------------------------------------------------------- |
| `events`                 | producing service or feature | `gateway`, `lifecycle`, `comments`        | ClickHouse `events`                                     |
| `operations_log`         | producing feature            | `deployments`, `maintenance`              | ClickHouse `operations_log`                             |
| `scheduler_runs`         | producing service            | `scheduler`                               | ClickHouse `scheduler_runs`                             |
| `metrics` (future)       | metric kind                  | `project-score`, `drift`, `pull-requests` | ClickHouse `metrics`, one wide time-series table for BI |
| `notifications` (future) | notification type            | `deployment`, `mention`, `digest`         | slackbot, email, and optionally ClickHouse for audit    |

The first three are the existing analytics tables, one stream each. The
`metrics` stream shows the sink model working with a topic dimension that
is not the producer: every metric kind lands in the same table, so one
sink with a static topic list covers it. The `notifications` stream shows
a subject whose primary consumers are Imbi services, not ClickHouse.

The gateway publishes every webhook delivery to one topic and puts the
webhook slug and integration slug in `user_headers`; the row itself
already carries both.

Message payload is the row as a JSON object, serialized by the existing
`imbi.common.clickhouse._dump` so aliases and enum values match what the
direct insert produces today. This is what the sink's default
`json_each_row` format consumes. Every topic is created with one
partition and published to with partition id 0, because the Python SDK
exposes only partition-id partitioning at this version; with a single
partition that is equivalent to balanced, and the sink flushes a stream
as one insert per batch, so partition-level order is enough.

### 2. Producer: `imbi.common.iggy` on the official `apache-iggy` SDK

A new module in `imbi-common` mirrors the shape of the ClickHouse client
and wraps `apache_iggy.IggyClient` over TCP:

- `settings.Iggy` reads `IGGY_URL` (`iggy+tcp://iggy:iggy@iggy:8090`, the
  SDK's connection-string form), `connect_timeout`,
  `max_connect_attempts`.
- `Iggy.get_instance()` singleton with `initialize()` (build the client
  from the connection string, `connect()`, retry with backoff like the
  ClickHouse client) and `aclose()`.
- `ensure_topic(stream, topic)` uses `get_stream`, `create_stream`,
  `get_topic`, `create_topic` and caches what it has created or seen so
  the calls happen once per process.
- `publish(stream, topic, models, *, columns=None)` accepts the same
  inputs as `clickhouse.insert` today plus the topic, builds one
  `SendMessage` per row with the JSON payload, and calls
  `send_messages` with balanced partitioning. The SDK raises
  `RuntimeError`; the module translates it to `iggy.PublishError` the
  way `clickhouse.DatabaseError` is.
- `TOPICS`, the stream-to-topics mapping, lives in this module and
  drives `ensure_topic`. It is the single source of truth for what the
  ClickHouse sink consumes: imbi-api renders the sink configuration from
  it (§3).
- Lifespan hooks in api, gateway, scheduler match the `clickhouse_hook`
  pattern. `entrypoint.sh` requires `IGGY_URL` in every mode.

`apache-iggy` is added to `imbi-common` as a `>=0.9.0.dev6` pre-release
pin until 0.9.0 ships. The image build gains a Rust toolchain in the
`python-builder` stage of `container/Dockerfile` so `uv sync` can compile
the sdist; the runtime stage is unchanged. Developers on Python 3.14 need
`rustup` locally for `uv sync` until upstream publishes a 3.14 wheel,
which is a one-line change to their `maturin --interpreter` list and
worth a PR.

### 3. Consumer: the official ClickHouse sink in our own Iggy image

We maintain our own Iggy image, the way
[AWeber-Imbi/postgres](https://github.com/AWeber-Imbi/postgres) wraps
PostgreSQL with Apache AGE and the other extensions Imbi needs. A new
repository, `AWeber-Imbi/iggy`, holds a Dockerfile and the connector
configuration, and publishes to `ghcr.io/aweber-imbi/iggy` on its own
release cadence:

1. A `rust` build stage checks out `apache/iggy` at a pinned commit and
   runs `cargo build --release -p iggy_connector_clickhouse_sink` for the
   glibc target of the build platform. Upstream does not ship this plugin
   as a binary and leaves it out of its own edge artifacts.
2. The image layers the `iggy-connectors` runtime and the compiled sink
   `.so` onto the matching `apache/iggy` server image, so one image
   carries the server, the runtime and the plugin. All three come from
   the same upstream commit because the plugin FFI is not versioned.
3. The image carries no sink configuration. The connectors runtime uses
   its HTTP configuration provider (`config_type = "http"`) and fetches
   the sink definitions from imbi-api at startup. The entrypoint runs the
   server or the connectors runtime depending on a mode variable, so the
   same image backs both containers in compose and both deployments in
   Helm. The Iggy address and credentials reach the runtime through
   `IGGY_CONNECTORS_*` environment variables.

imbi-api implements the provider contract: one sink per ClickHouse-bound
stream in `TOPICS`, rendered with `schema = "json"`,
`insert_format = "json_each_row"`, `batch_length = 1000`,
`poll_interval = "250ms"`, a consumer group named after the table, and a
`plugin_config` whose ClickHouse URL, database and credentials come from
the api's own `settings.Clickhouse`. The endpoint is protected by a
static api key the runtime sends in a request header, because the
response carries ClickHouse credentials. Environment overrides cannot
reach `plugin_config` (the runtime marks it as not env-addressable),
which is why the credentials travel in the served configuration rather
than in the connectors container's environment.

Iggy stores consumer-group offsets server side, so a runtime restart
resumes where it left off, and more than one runtime replica can join the
same group. Adding a topic is a change to `TOPICS` followed by a restart
of the connectors runtime; the runtime's own HTTP API can also restart a
single sink. The two-list failure mode, a topic Imbi publishes to that no
sink consumes, cannot occur: there is one list.

### 4. Read-after-write paths

Sink lag is bounded by the poll interval plus one insert, well under a
second. Two paths are still changed to tolerate lag rather than left on
the direct client:

- **`operations_log.complete_opslog_entry`**: keep the read, but when no
  open row is found retry once after one poll interval before logging the
  no-op. The start webhook and the completion webhook are seconds to
  minutes apart in practice, so the retry is a safety net, not the path.
- **Scheduler runs**: `POST /tasks/{slug}/run` already returns the `Run`
  object it built rather than re-reading it. `GET /runs/{id}` may miss a
  run for one tick; the UI polls, so no change is needed. The engine's
  "unsuperseded running row" diagnostic is unaffected.
- **SBOM batch ordering**: `release_components` and
  `release_component_batches` are separate streams consumed by separate
  sinks, so cross-stream order is not guaranteed. `sbom.py` publishes the
  batch row only after the fact rows are acknowledged, and readers keep
  ranking by `(source, recorded_at)` and `batch_id`. A batch row visible
  before its last fact rows is a window of one poll interval.

No table keeps a direct insert path once phase 4 lands. Keeping two write
paths is exactly the state this ADR removes.

### 5. Duplicates on plain MergeTree tables

`score_history`, `release_components`, `release_component_batches` and
`maintenance_log` would keep duplicate rows after a redelivery. Handling:

- `release_components` and `release_component_batches` already carry a
  `batch_id`; readers rank by batch, so a duplicate batch is harmless.
- `maintenance_log` is observability; a duplicate attempt row is noise,
  not a wrong answer. Accept it.
- `score_history` feeds `score_latest` through an aggregating view. A
  duplicate row for the same `(project_id, recorded_at)` does not change
  the latest value. Accept it, and note it in the table's comment.

If any of these later needs exact-once semantics, the fix is a
`ReplacingMergeTree` conversion keyed on the row's natural key, not
consumer-side dedup.

### 6. Local and CI environment

`compose.yaml` and `compose.ci.yaml` already carry an `iggy` service on
the TCP port `8090`, which is all the producers need. Switch its image
to `ghcr.io/aweber-imbi/iggy`, keep the HTTP port enabled for the health
check and for inspection, set `IGGY_SYSTEM_SHARDING_PIN_CORES=false`
(Iggy 0.9 binds shard memory to NUMA nodes, which the Docker Desktop VM
does not support), and add an `iggy-connect` service from the same image
in connectors mode that depends on `iggy`, `clickhouse` and the api
serving its configuration. `moon run root:services` writes `IGGY_URL`
into `.env.test` next to `CLICKHOUSE_URL`.

Tests for the producer mock `IggyClient` at the module boundary. Existing
tests that patch `clickhouse.insert` move to patching `iggy.publish`. One
end-to-end test in `apps/gateway/tests` publishes a delivery and reads
the row back from ClickHouse through the sink, with a bounded wait.

## Rollout

Each phase is one PR and leaves the tree releasable.

1. **Infrastructure and common module.** `settings.Iggy`,
   `imbi.common.iggy` with `TOPICS`, lifespan hooks, compose and
   `.env.test` wiring, `entrypoint.sh` and Helm `IGGY_URL`, README and
   `docs/deployment` tables. No call site changes. Verify: `moon ci`
   green; `imbi.common.iggy` unit tests pass against a mocked
   `IggyClient`.
2. **Iggy image.** The `AWeber-Imbi/iggy` repository: Dockerfile with
   the plugin build, entrypoint with server and connectors modes,
   multi-arch publish to ghcr. In this repository: the configuration
   provider endpoint in imbi-api, compose services, Helm deployment for
   the connectors runtime, docs page. Verify: the end-to-end test
   publishes to `events/gateway` and reads the row back from ClickHouse.
3. **Gateway.** `DeliveryRecorder` publishes to `events/gateway` for both
   phases. Verify: `test_notifications.py` assertions on `insert` become
   assertions on `publish`; the end-to-end test from phase 2 runs against
   the real recorder.
4. **API, scheduler, plugins.** Replace the remaining call sites from the
   table above, including the `complete_opslog_entry` retry and the sbom
   publish order. Verify: each member's suite; a grep for `.insert(`
   outside `imbi.common.clickhouse` returns nothing.
5. **Remove the direct insert path.** Delete `clickhouse.insert` and
   `Clickhouse.insert`; `setup_schema` and `query` remain. Update
   `libraries/common/README.md`.

Estimated effort: phase 1 one day, phase 2 one day, phase 3 half a day,
phase 4 two days, phase 5 half a day.

## Consequences

- Rows reach ClickHouse a few hundred milliseconds after the request
  instead of before the response. Every reader of these tables already
  tolerates `ReplacingMergeTree` convergence, so this is a narrower
  change than it sounds, and §4 lists the places that needed a look.
- Iggy becomes a required backing service for every mode, like
  ClickHouse and PostgreSQL, and the bus that later streams build on
  under the conventions in §1. A down Iggy fails requests that record
  events the same way a down ClickHouse does today; a down ClickHouse no
  longer does, because the stream absorbs the outage.
- We maintain an Iggy image alongside the PostgreSQL one. It is a thin
  layer over upstream plus the connectors runtime and one compiled
  plugin, all built from one pinned upstream commit, and the connectors
  runtime in it is the only writer to the analytics tables.
- We carry a Rust toolchain in two image builds: the Iggy image compiles
  the ClickHouse plugin, and this repository's Python builder stage
  compiles the `apache-iggy` sdist. The second goes away once upstream
  ships a CPython 3.14 wheel.
- The connectors runtime depends on imbi-api at its own startup to fetch
  configuration, and imbi-api holds the only list of sinks. A runtime
  that starts before the api retries; a topic added to `TOPICS` is
  consumed after the next runtime restart.
- Per-webhook filtering happens in ClickHouse on `metadata.webhook_id`
  and `integration`, not by topic. If a webhook ever needs its own
  topic, the runtime API can version and restart a sink configuration;
  that path is deliberately not taken here.
- Operators can inspect what a service emitted by reading its topic, and
  replay a stream into ClickHouse by resetting one consumer-group offset.
- Streams whose consumers are Imbi services rather than ClickHouse (the
  future `notifications` stream) are out of scope here. The consumer
  side for those is a separate decision.

## Alternatives considered

- **Valkey Streams.** Already in the stack, but no sink ecosystem, no
  per-topic retention or partitioning, and a history bounded by memory.
  Fine for a work queue, not for a replayable record.
- **Kafka or RabbitMQ streams.** Mature, but a cluster and an operator
  to run for a platform of Imbi's size. Iggy gives the same stream and
  consumer-group model as a single binary. We also do not need the complex
  routing topologies that RabbitMQ can provide.
- **A Python consumer service (`imbi-ingest`).** Rejected: it
  re-implements batching, offsets and retries that the sink already has,
  and adds a service to the image and chart. It was only attractive when
  topics were dynamic.
- **Topic per webhook with a dynamically regenerated sink config.**
  Rejected: imbi-api would gain an outbound dependency on the connectors
  runtime, and a webhook created while the runtime is down publishes to a
  topic nothing drains until the next restart.
- **Iggy HTTP API through `httpx`.** Viable and dependency-free, but it
  re-implements login, token refresh and batching the SDK already has,
  and gives up the SDK's reconnection handling. Kept as the fallback if
  the sdist build becomes a burden.
- **Header-based routing with one stream.** Rejected: the sink has no
  header routing, and a stream that mixes tables cannot be replayed into
  one table without filtering.
- **ClickHouse `async_insert` everywhere.** Solves part count but not the
  coupling to ClickHouse availability, and gives no per-service record.
