# Operations

This page tells you how to operate Imbi in production: Apache Iggy and the
connectors runtime, ClickHouse, metrics, Sentry, logging, and backups. It
ends with a production checklist.

For the upgrade steps of each release, see [Upgrading](upgrading.md).

## Apache Iggy

Imbi does not write to ClickHouse directly. Each service publishes the rows
to Apache Iggy. The Iggy connectors runtime (iggy-connect) reads the rows
and inserts them into ClickHouse.

- Each stream has the name of the ClickHouse table that it fills, for
  example `operations_log`. A stream has one or more topics. Each topic has
  one partition.
- iggy-connect runs one ClickHouse sink for each stream. The sink reads the
  stream as a consumer group that has the name of the stream.
- `imbi.common.iggy.TOPICS` in the code is the list of streams and topics.
  imbi-api makes the sink configuration from that list.
- Each Imbi service creates the streams and topics that are missing when it
  starts.

### Run the Iggy server

The Imbi chart and the Compose file do not give Iggy persistent storage.
In production:

- Keep the Iggy data directory on a persistent volume. If the volume is
  lost, the rows that iggy-connect did not write to ClickHouse are lost.
- Change the root credentials (`IGGY_ROOT_USERNAME`, `IGGY_ROOT_PASSWORD`).
  Put the same credentials in `IGGY_URL` and in the iggy-connect settings.
- Imbi uses the TCP listener (port 8090 in the examples). The `iggy` CLI in
  the image also uses TCP by default.

Use the same Iggy image version for the server and for iggy-connect. The
examples use `ghcr.io/aweber-imbi/iggy:0.9.0-edge.6-0`.

### When to restart iggy-connect

iggy-connect reads its sink configuration from imbi-api one time, at
startup. Restart it in these cases:

| Event | Why |
|---|---|
| A release adds a stream | The new stream gets no sink until the restart. Run `imbi-api setup-clickhouse` first, because the sink writes to the table of the same name |
| The Iggy server restarted | iggy-connect can stop and not connect again. Then also look for a ghost member (next section) |
| You changed the connectors API key | iggy-connect sends the key only when it starts |

iggy-connect stops when imbi-api does not answer, or when a stream that it
must read does not exist. Run it with a restart policy (`restart:
on-failure` in Compose; Kubernetes restarts it by default). A restart
after imbi-api is up corrects both problems.

The Imbi services connect to Iggy again by themselves after an Iggy
restart. You do not have to restart them.

### Ghost consumer-group members

An Iggy consumer group can keep a member whose client is gone
([apache/iggy#4273](https://github.com/apache/iggy/issues/4273)). That
member keeps the partition. The live iggy-connect member gets no partition,
and its polls return nothing. There is no error in the logs. Rows stay in
Iggy and do not get to ClickHouse.

This can occur after each Iggy server restart. Look for it after every
restart.

#### Find it

Use one of these:

- The **Iggy topics** card on the admin overview. A topic whose
  **Members** count is more than its **Owning** count shows in red, and the
  card header shows `N unowned`.
- The metrics `imbi_iggy_consumer_group_members` and
  `imbi_iggy_consumer_group_members_owning` (see [Metrics](#metrics)).
  Members more than owning members is the problem.
- The `iggy` CLI in the Iggy server container:

    ```bash
    iggy --credentials-username <user> --credentials-password <password> \
      consumer-group get <stream> <topic> <stream>
    ```

    The third argument is the group, which has the name of the stream. A
    member with 1 partition next to members with 0 partitions is the
    problem.

- The offset files on the disk of the Iggy server. The server keeps the
  stored offset of each consumer group in a file under
  `streams/<stream id>/topics/<topic id>/partitions/0/offsets/groups/<group id>`
  in its data directory. The ids are numbers. If the modification time of
  the group offset file does not change while the `.log` files of the
  partition grow, the group reads nothing. This layout was seen on Iggy
  0.9.0-edge.8. Other versions can be different.

#### Fix it

1. Stop iggy-connect (scale it to 0).
2. For each topic of each affected stream, delete the group and create it
   again:

    ```bash
    iggy --credentials-username <user> --credentials-password <password> \
      consumer-group delete <stream> <topic> <stream>
    iggy --credentials-username <user> --credentials-password <password> \
      consumer-group create <stream> <topic> <stream>
    ```

3. Start iggy-connect.
4. Make sure that each group has one member that owns the partition, and
   that new rows get to ClickHouse.

The delete removes the stored offset. You cannot set the offset back with
`iggy consumer-offset set`, because Iggy 0.9 lets only the owning member
store a group offset. Thus the new group reads the stream again from the
oldest message that Iggy keeps. The next section tells what this does to
each table.

### Read a stream again (replay)

When a group reads a stream again, the sink inserts the rows again.

- The tables with a `ReplacingMergeTree` engine remove the duplicates when
  ClickHouse merges their parts.
- These tables use a plain `MergeTree` engine and keep the duplicates:
  `score_history`, `release_components`, `release_component_batches`,
  `maintenance_log`, and `email_audit`.

After a replay of one of these streams, remove the duplicates:

```sql
OPTIMIZE TABLE imbi.<table> FINAL DEDUPLICATE;
```

A replay of `score_history` also changes the materialized view
`score_latest_data`. Make it again from `score_history` after the
`OPTIMIZE`.

!!! warning
    Seen with the Iggy 0.9.0-edge connectors runtime: when ClickHouse
    refuses an insert and the retries fail, the sink still stores the new
    offset. The rows of that batch do not get to ClickHouse, and no
    restart sends them again. Only a replay gets them back. This is
    behavior of the connectors runtime, not of Imbi. Imbi configures 3
    retries with a delay of 1 second.

## ClickHouse

### Create the schema

Imbi does not create ClickHouse tables at startup. `imbi-api setup` and
`imbi-api setup-clickhouse` create them. Run `setup-clickhouse` after each
release that adds a table (see [Upgrading](upgrading.md)).

- The DDL is in `libraries/common/src/imbi/common/clickhouse/schemata.toml`.
  Each statement is `CREATE ... IF NOT EXISTS`. A second run creates only
  the missing objects, and it does not change a table that exists.
- The DDL names the database `imbi`. Create a database with that name
  before setup, and use it in `CLICKHOUSE_URL`.
- When one statement fails, the command logs the error and continues with
  the next statement. Read the output.
- A table that does not exist causes `UNKNOWN_TABLE` errors on reads, and
  iggy-connect cannot write its stream.

### Clusters

Set `CLICKHOUSE_CLUSTER_NAME` to the name of your ClickHouse cluster when
you run more than one ClickHouse node. Then `setup-clickhouse`:

- adds `ON CLUSTER <name>` to each statement, and
- uses the `Replicated` variant of each table engine.

The replicated engines use the `default_replica_path` and
`default_replica_name` settings of the server for the Keeper path and the
replica name. Set them on each server.

Keep ClickHouse Keeper (or ZooKeeper) on persistent volumes. If Keeper
loses its data, every replicated table becomes read-only. Then
`SYSTEM RESTORE REPLICA` on each table makes the Keeper metadata again from
the local parts.

Leave `CLICKHOUSE_CLUSTER_NAME` unset for one node.

### Retention

These tables have a TTL. The other tables keep their rows until you
delete them.

| Table | Rows are deleted after |
|---|---|
| `scheduler_runs` | 90 days |
| `document_read_events` | 90 days |
| `maintenance_log` | 90 days |
| `email_audit` | 1 year |
| `document_read_sessions` | 2 years |

## Metrics

imbi-api, imbi-gateway, and imbi-scheduler serve Prometheus metrics at
`/metrics` on their own port (8000, 8003, and 8005). The path is on the
root of the service, not under the API prefix. It has no authentication.
Let Prometheus scrape the pods directly. Do not expose the path publicly.
The bundled Caddy does not route `/metrics`, and it answers 404 for
`/gateway/metrics` and `/scheduler/metrics`.

iggy-connect serves its own metrics at `/metrics` on port 8081.

The other services (imbi-assistant, imbi-mcp, imbi-slackbot,
imbi-workflows) serve no metrics.

For the scrape annotations that the Helm chart adds, see
[Kubernetes: Metrics](kubernetes.md#metrics).

| Metric | Type | Labels | Exported by |
| --- | --- | --- | --- |
| `imbi_iggy_published_total` | counter | `stream`, `topic` | api, gateway, scheduler |
| `imbi_iggy_publish_errors_total` | counter | `stream`, `topic` | api, gateway, scheduler |
| `imbi_iggy_topic_status_up` | gauge | none | api |
| `imbi_iggy_topic_current_offset` | gauge | `stream`, `topic` | api |
| `imbi_iggy_topic_messages` | gauge | `stream`, `topic` | api |
| `imbi_iggy_consumer_group_members` | gauge | `stream`, `topic` | api |
| `imbi_iggy_consumer_group_members_owning` | gauge | `stream`, `topic` | api |
| `imbi_harness_pool_queued` | gauge | `pool` | api |
| `imbi_harness_runners` | gauge | `pool`, `state` | api |
| `imbi_harness_chains` | gauge | `state` | api |
| `imbi_harness_metrics_up` | gauge | none | api |

- The two counters count messages, one for each row, in the process that
  published them. Each topic in `imbi.common.iggy.TOPICS` starts at 0.
- The `imbi_iggy_topic_*` and `imbi_iggy_consumer_group_*` gauges come from
  the same read as the **Iggy topics** card. Each imbi-api pod reads them
  every 30 seconds and reports the same global values, so aggregate them
  with `max()`.
- `imbi_iggy_topic_status_up` is 0 when the last read failed or took more
  than 10 seconds. The other gauges then keep the values of the last good
  read.
- The `imbi_harness_*` gauges describe the agent runner pools. See
  [Agent Runners: Metrics](agent-runners.md#metrics).

Recommended alerts:

| Condition | Meaning |
|---|---|
| `max by (stream, topic) (imbi_iggy_consumer_group_members) > max by (stream, topic) (imbi_iggy_consumer_group_members_owning)` | A ghost member. See [Ghost consumer-group members](#ghost-consumer-group-members) |
| `max(imbi_iggy_topic_status_up) == 0` | imbi-api cannot read the Iggy topic status |
| `increase(imbi_iggy_publish_errors_total[5m]) > 0` | A service cannot publish to Iggy |

## Sentry

Set `SENTRY_DSN` to send errors to Sentry. Without it, Sentry is off.

| Variable | What it does |
|---|---|
| `SENTRY_DSN` | The DSN. imbi-api, imbi-assistant, imbi-mcp, and imbi-slackbot read it. imbi-gateway, imbi-scheduler, and imbi-workflows do not send to Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | The fraction of requests to trace, for example `0.1`. The default is `0.0`, which turns tracing off. Imbi never traces `/status` |
| `SERVICE` | The server name in Sentry. The default is `unknown`. In `all` mode, all services in the container use the same value |
| `VITE_SENTRY_DSN` | The DSN of the UI. Caddy writes it into the page when it serves the UI. The UI traces 10% of page loads |

Imbi sends no personal data, and no request bodies. For the secret broker
routes and modules, it also removes the query string and the local
variables of the stack frames.

To upload the UI source maps to Sentry, set `SENTRY_AUTH_TOKEN`,
`SENTRY_ORG`, and `SENTRY_PROJECT` on the container (`all` or `ui` mode).
`SENTRY_RELEASE` and `SENTRY_URL` are optional. The container uploads the
maps when it starts. Caddy serves the `.map` files only when
`SERVE_SOURCE_MAPS` is `true`.

## Logging

Each service writes its logs as text to standard output. The level is
`INFO`. Collect the container output with your log platform.

- imbi-api, imbi-gateway, imbi-mcp, and imbi-scheduler write one access
  log line for each request. The line shows the user of the request: the
  local part of the JWT subject, or the name of the API key. In imbi-api,
  imbi-gateway, and imbi-scheduler, a successful request to `/status` or
  `/metrics` writes no line. A failed one does.
- imbi-api, imbi-assistant, imbi-gateway, imbi-scheduler, imbi-slackbot,
  and imbi-workflows use the `serve` command. Its `--verbose` option sets
  the service logger to `DEBUG`, and `--log-config <file>` reads a TOML
  logging configuration (the format of `logging.dictConfig`). The default
  configuration is `libraries/common/src/imbi/common/log-config.toml`. The
  container entrypoint does not set these options, so change the container
  command to use them.

## Backups

Back up these data stores:

| Store | What it holds | How |
|---|---|---|
| PostgreSQL | The graph (Apache AGE), the embeddings, and the relational schemas of the scheduler, agent tasks, workflows, secrets, and runner pools | `pg_dump`. See [Restore a Backup](../api/restore-backup.md) |
| ClickHouse | The operations log, events, commits, tags, pull requests, score history, and audit tables | `BACKUP` and `RESTORE` of ClickHouse, or an export of each table |
| Iggy | Rows that iggy-connect did not write yet | Keep the data directory on a persistent volume. You do not have to back it up |
| S3 | Uploaded files | The backup tools of your object store |

### PostgreSQL

Back up the whole database with `pg_dump`. Do not select schemas. The
database holds the graph schema (`imbi`), the AGE catalog (`ag_catalog`),
the embeddings table (`public.embeddings`), and the `scheduler`,
`agent_runtime`, `workflows`, `workflow_runtime`, `secrets`, and `harness`
schemas.

```bash
pg_dump --dbname "$POSTGRES_URL" --format custom --no-owner \
  --no-privileges --file imbi.dump
```

The server that you restore to needs the `age`, `pg_cron`, and `vector`
extensions. The [`ghcr.io/aweber-imbi/postgres`](kubernetes.md#postgresql-with-cloudnativepg)
image has all three.

### ClickHouse

Use the `BACKUP` and `RESTORE` statements of ClickHouse to back up the
`imbi` database. They need a backup destination in the server
configuration. See the ClickHouse documentation.

Another method is to export each table:

```sql
SELECT * FROM imbi.<table> FORMAT Native
```

Export the tables only. Do not export the materialized views or their
`.inner` tables. After you load the tables into a new server, the views
fill again from the new rows only. Make `score_latest_data` again from
`score_history`.

Before you restore, run `imbi-api setup-clickhouse` on the new server to
create the tables.

## Production checklist

Configuration:

- [ ] Set `ENVIRONMENT=production` on every service. Then Imbi refuses to
      start without `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, and
      `IMBI_CONFIG_ENCRYPTION_KEY`. When `ENVIRONMENT` is unset, each
      process makes its own keys, and the services cannot decrypt the
      values of other services or of a previous start.
- [ ] Give every service the same three keys. Keep a copy of the keys in
      a safe place. Without them, you cannot decrypt a restored database.
- [ ] Set `IMBI_API_URL` to the public API URL, with the `/api` path, and
      `VITE_API_URL` to the same value.
- [ ] Set `IMBI_UI_URL` to the public UI URL.
- [ ] Set `IMBI_API_CORS_ALLOWED_ORIGINS` and
      `IMBI_API_FORWARDED_ALLOW_IPS` for your proxy and your UI origin.
- [ ] Set `VALKEY_URL`. Without Valkey, imbi-api does not start its
      background workers.
- [ ] Set `IMBI_INTERNAL_*_URL` on imbi-api for each service that the
      **System health** card must show.
- [ ] Pin the image tag. Do not use `latest`.

Services:

- [ ] Run iggy-connect, and set the same key in
      `IMBI_IGGY_CONNECTORS_API_KEYS` and `IGGY_CONNECTORS_API_KEY`.
- [ ] Keep Iggy, ClickHouse, ClickHouse Keeper, and PostgreSQL data on
      persistent volumes.
- [ ] Run `imbi-api setup` one time, then restart the `all` mode container
      so that imbi-scheduler and imbi-workflows start.

Monitoring and recovery:

- [ ] Scrape `/metrics` of imbi-api, imbi-gateway, imbi-scheduler, and
      iggy-connect, and add the alerts in [Metrics](#metrics).
- [ ] Set `SENTRY_DSN`.
- [ ] Back up PostgreSQL and ClickHouse, and test a restore.
- [ ] After each Iggy server restart, restart iggy-connect and look for
      ghost consumer-group members.

With the Helm chart, set the variables that have no chart value with
`extraEnv`. See
[Kubernetes: Extra environment variables](kubernetes.md#extra-environment-variables).
