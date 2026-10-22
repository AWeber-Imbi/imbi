# Kubernetes Deployment

Imbi provides a Helm chart for deploying to Kubernetes. The chart does not
bundle databases — it expects PostgreSQL (with the Apache AGE extension) and
ClickHouse to be provisioned externally. The recommended approach is to run
them with their respective Kubernetes operators:

- **PostgreSQL** — [CloudNativePG](https://cloudnative-pg.io/) with an
  AGE-enabled image
- **ClickHouse** — the [Altinity ClickHouse operator](https://github.com/Altinity/clickhouse-operator)

## Prerequisites

- Kubernetes 1.28+
- Helm 3.x
- The [CloudNativePG operator](https://cloudnative-pg.io/documentation/current/installation_upgrade/)
  installed in the cluster (or another AGE-enabled PostgreSQL)
- The [Altinity ClickHouse operator](https://github.com/Altinity/clickhouse-operator)
  installed in the cluster (or another ClickHouse instance)

## What the Chart Cannot Do Yet

The chart cannot set these variables. Issue
[#459](https://github.com/AWeber-Imbi/imbi/issues/459) tracks the fix.

- **`ENVIRONMENT` and `IMBI_CONFIG_ENCRYPTION_KEY`.** Every chart install
  runs with `ENVIRONMENT` unset, which is `development`. Each process then
  generates its own configuration encryption key. Encrypted configuration
  values, such as AI provider keys, cannot be decrypted after a restart or by
  another process.
- **`VALKEY_URL`.** imbi-api starts without Valkey, but its background
  workers (commit, pull request, and deployment sync, release promotion,
  maintenance, and the sweepers) do not start.
- **`VITE_API_URL`.** The UI reads the API URL from this variable. Without
  it, the UI does not load in `all` and `ui` mode.
- **Other variables.** The chart has no `extraEnv` or `extraEnvFrom` value.
  It cannot set, for example, `IMBI_UI_URL`, CORS, MCP OAuth, Sentry, SMTP
  authentication, or the Slack tokens. Thus `service.mode: slackbot` cannot
  start.

## Installing the Chart

!!! warning
    The published 2.39.0 image fails at startup on a new Iggy server: imbi-api
    cannot create its Iggy topics and exits. See
    [issue #469](https://github.com/AWeber-Imbi/imbi/issues/469).

1. Put the five required values in a values file. The chart refuses to
   render without the connection URLs.

    ```yaml
    auth:
      jwtSecret: "your-jwt-secret"
      encryptionKey: "your-fernet-key"
    externalPostgresql:
      url: postgresql://imbi:password@imbi-pg-rw:5432/imbi
    externalClickhouse:
      url: clickhouse+http://default:password@clickhouse-imbi:8123/imbi
    externalIggy:
      url: iggy+tcp://iggy:iggy@imbi-iggy:8090
    service:
      publicApiUrl: https://imbi.example.com/api
    ```

    `service.publicApiUrl` is the public URL of the API. imbi-api mounts its
    routes under its path, and the bundled Caddy sends `/api/*` to imbi-api,
    so the path must be `/api`. Without it, every API call through Caddy gets
    a 404.

2. Install the chart:

    ```bash
    helm install imbi helm/imbi -f values.yaml --namespace imbi --create-namespace
    ```

3. Run setup in the pod. The Deployment name is the release name, or
   `<release>-imbi` when the release name does not contain `imbi`:

    ```bash
    kubectl -n imbi exec deploy/imbi -- imbi-api setup-postgres
    kubectl -n imbi exec -it deploy/imbi -- imbi-api setup
    ```

    `setup-postgres` creates the PostgreSQL schema that setup needs. It does
    nothing when imbi-api has already created the schema.

    See [Initial Setup](../getting-started/setup.md) for the prompts.

4. Restart the Deployment. In `all` mode, imbi-scheduler and imbi-workflows
   start only when the container seeds the internal service accounts at
   startup, and that fails before setup has run:

    ```bash
    kubectl -n imbi rollout restart deployment/imbi
    ```

## Configuration

### Image Configuration

```yaml
image:
  repository: ghcr.io/aweber-imbi/imbi
  tag: latest
  pullPolicy: IfNotPresent
```

### Service Scaling

Run all services in a single pod (default) or scale individually:

```yaml
# All-in-one mode (default)
service:
  mode: all

# Scaled-out mode — one service per release
service:
  mode: api        # or assistant, gateway, mcp, scheduler, slackbot, ui,
                   # workflows
  api:
    replicas: 3
  assistant:
    replicas: 1
  gateway:
    replicas: 2
  mcp:
    replicas: 1
  scheduler:
    replicas: 1
  slackbot:
    replicas: 1
  workflows:
    replicas: 1
  ui:
    replicas: 2
    upstreams:
      api: imbi-api:8080
      mcp: imbi-mcp:8080
      assistant: imbi-assistant:8080
      gateway: imbi-gateway:8080
      scheduler: imbi-scheduler:8080
```

In scaled-out mode the `ui` release is the one to put behind the ingress: it
runs the bundled Caddy alone, serving the UI and proxying every other path to
the service named in `service.ui.upstreams`, so the URL layout is the same as
in `all` mode.

Every Service that the chart creates listens on port 8080, whatever the
mode. The Service sends the traffic to the container port of the mode. Use
port 8080 for every in-cluster URL in this page. The Service name follows
the same rule as the Deployment name.

### Scheduler

The scheduler runs every task as its own service account, so give it a
credential. The account is not seeded: create a service account in the UI,
grant it the `scheduled_task:*` permissions plus whatever its tasks need, and
issue it a client credential.

```yaml
scheduler:
  serviceAccount:
    clientId: "imbi-scheduler-client-id"
    clientSecret: "imbi-scheduler-client-secret"
```

Without them the pod still starts and still schedules, but resolves no
principal for an `api` target, so every such firing is recorded as `skipped`.

When the scheduler runs as its own pod, it also needs to know where imbi-api
is — both where to *connect* and what path imbi-api mounts its routes under:

```yaml
service:
  mode: scheduler
  internalApiUrl: http://imbi-api.imbi.svc.cluster.local:8080
  publicApiUrl: https://imbi.example.com/api
```

The chart refuses to render in `scheduler` mode if `internalApiUrl` is left at
the loopback default — there it resolves to the scheduler's own pod, which
reports healthy while every `api`-target firing fails. More than one replica is
safe: due firings are claimed with `FOR UPDATE SKIP LOCKED`, so replicas take
disjoint claims. See
[Scheduler configuration](../scheduler/configuration.md).

Using `existingSecret`, the scheduler reads the optional
`scheduler-sa-client-id` and `scheduler-sa-client-secret` keys from it.

### Workflows

The `imbi-workflows` worker runs workflow runs. It listens on port 8006. In
`all` mode it starts in the same pod as the other services. To run it as
its own release, set `service.mode: workflows`:

```yaml
service:
  mode: workflows
  internalApiUrl: http://imbi-api.imbi.svc.cluster.local:8080
  publicApiUrl: https://imbi.example.com/api
  workflows:
    replicas: 1

workflows:
  serviceAccount:
    clientId: "imbi-workflows-client-id"
    clientSecret: "imbi-workflows-client-secret"
  schedulerUrl: http://imbi-scheduler.imbi.svc.cluster.local:8080/api
```

- The chart refuses to render in `workflows` mode when `internalApiUrl` is
  the loopback default or `publicApiUrl` is empty.
- `imbi-api setup` seeds the `imbi-workflows` service account with the
  `workflows.serviceAccount` values, as it does for the scheduler. Set both
  values or neither. Using `existingSecret`, the worker reads the
  `workflows-sa-client-id` and `workflows-sa-client-secret` keys from it.
  In `workflows` mode the container does not start without them.
- `workflows.schedulerUrl` is imbi-scheduler's task API, with its route
  prefix. The worker writes the scheduler task of each schedule trigger
  there. Empty uses `http://localhost:8005/api`, which works in `all` mode
  only.
- More than one replica is safe. A replica claims a run with
  `FOR UPDATE SKIP LOCKED` and holds it with a lease.

See [Workflows](../admin/workflows.md).

### Agent runners

Agent tasks run on runner pods from a separate chart, `helm/imbi-harness`.
Install one release for each runner pool, in its own namespace. See
[Agent Runners](agent-runners.md).

### Database Configuration

The chart does not deploy databases. Point it at your external PostgreSQL
(Apache AGE) and ClickHouse instances:

```yaml
externalPostgresql:
  url: postgresql://imbi:password@imbi-pg-rw:5432/imbi

externalClickhouse:
  url: clickhouse+http://default:password@clickhouse-imbi:8123/imbi
```

#### PostgreSQL with CloudNativePG

Imbi's graph database is PostgreSQL with the Apache AGE extension. Create a
CloudNativePG `Cluster` using an AGE-enabled image before installing the chart:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: imbi-pg
spec:
  instances: 3
  imageName: ghcr.io/aweber-imbi/postgres:18.3-1
  postgresql:
    shared_preload_libraries:
      - age
      - pg_cron
    parameters:
      cron.database_name: imbi
  bootstrap:
    initdb:
      database: imbi
      owner: imbi
      postInitSQL:
        - CREATE EXTENSION IF NOT EXISTS age
  storage:
    size: 20Gi
```

CloudNativePG exposes the primary at `<cluster-name>-rw` (here `imbi-pg-rw`)
and stores the generated `imbi` user's password in the `imbi-pg-app` secret.
Use those to build `externalPostgresql.url`.

!!! note
    CloudNativePG's operand-image requirements are minimal — standard
    PostgreSQL binaries, a proper locale, and a PGDG-supported version — and
    the official-postgres-based `ghcr.io/aweber-imbi/postgres` image (Apache
    AGE, pg_cron, pgvector) satisfies them. Two caveats: the image **tag must
    begin with the PostgreSQL major version** (e.g. `18.3-1`); CNPG rejects
    `latest` for version detection. And because CNPG generates its own
    `postgresql.conf`, set `shared_preload_libraries` in the Cluster spec
    rather than relying on the image's baked config.

#### ClickHouse with the Altinity operator

Provision ClickHouse with a `ClickHouseInstallation` resource, then point
`externalClickhouse.url` at the service the operator creates (typically
`clickhouse-<installation-name>`).

### Apache Iggy

Every Imbi service connects to Apache Iggy at startup and provisions the
streams it publishes to, so `externalIggy.url` is required — the chart
refuses to render without it. The chart does not deploy Iggy; run the server
from the same image the connectors runtime uses, in its default `server`
mode:

```yaml
externalIggy:
  url: iggy+tcp://iggy:iggy@imbi-iggy:8090
```

### The connectors runtime

Rows bound for ClickHouse travel through Iggy, and it is the connectors
runtime that drains each stream into its table (see ADR 0019, Apache
Iggy message streaming). Turning
`iggyConnect.enabled` on adds a second Deployment from the Iggy image:

```yaml
iggyConnect:
  enabled: true
  apiKey: "invent-one-here"
  iggy:
    address: imbi-iggy:8090
    username: iggy
    password: iggy

service:
  publicApiUrl: https://imbi.example.com/api
```

Two things to know before enabling it:

- **It fetches its sink configuration from imbi-api, once, at startup.** The
  configuration is generated from the streams Imbi publishes to, so a release
  that adds a stream needs `kubectl rollout restart deployment/<release>-connect`
  before that stream is consumed. Nothing polls.
- **That response carries the ClickHouse credentials**, so the endpoint serving
  it is authenticated with `iggyConnect.apiKey`, which reaches imbi-api as
  `IMBI_IGGY_CONNECTORS_API_KEYS` and the runtime as `IGGY_CONNECTORS_API_KEY`.
  Rotate by setting the value to `old,new`, rolling imbi-api, then rolling the
  connectors Deployment onto the new key alone.

In `all` mode the API sits behind the bundled Caddy, which forwards only
`/api/*` to imbi-api, so `service.publicApiUrl` has to carry a path. The chart
refuses to render otherwise rather than pointing the runtime at the SPA. Set
`iggyConnect.configBaseUrl` to reach an imbi-api Service directly when the API
is a separate release:

```yaml
iggyConnect:
  configBaseUrl: http://imbi-api:8080/api/iggy/connectors
```

The runtime exits when imbi-api is unreachable or a stream it is configured
for does not exist yet. Both are states a restart resolves, so the Deployment
is left to restart into them.

### Metrics

imbi-api, imbi-gateway and imbi-scheduler serve Prometheus metrics at
`/metrics` on their own port (8000, 8003 and 8005). The path is on the app
root, not under the API prefix, and has no authentication: Prometheus scrapes
it by pod IP. The bundled Caddy does not route it. The chart adds the
`prometheus.io/scrape`, `prometheus.io/port` and `prometheus.io/path` pod
annotations in `api`, `gateway` and `scheduler` mode. In `all` mode the three
services share one pod, and the annotations name imbi-api on port 8000 only,
so the gateway and scheduler counters are not scraped. The connectors runtime
pod is annotated for its own metrics on port 8081. The `workflows` mode pod
has no metrics annotations.

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

- The two counters count messages, one per row, in the process that
  published them. Every topic in `imbi.common.iggy.TOPICS` starts at 0.
- The gauges come from the same read as the admin Iggy dashboard. Each
  imbi-api pod refreshes them every 30 seconds and reports the same global
  values, so aggregate them with `max()`.
- `imbi_iggy_topic_status_up` is 0 when the last refresh failed or took more
  than 10 seconds. The other gauges then keep the values of the last good
  refresh.
- A consumer group with more members than owning members has a member that
  reads nothing (apache/iggy#4273), and its topic does not drain.
- The `imbi_harness_*` gauges describe the agent runner pools. Each
  imbi-api pod refreshes them every 15 seconds and reports the same global
  values, so aggregate them with `max()`. `imbi_harness_metrics_up` is 0
  when the last refresh failed. See
  [Agent Runners: Metrics](agent-runners.md#metrics).

### Ingress

```yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: imbi.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: imbi-tls
      hosts:
        - imbi.example.com
```

## Upgrading

1. Upgrade the release:

    ```bash
    helm upgrade imbi helm/imbi -f values.yaml --namespace imbi
    ```

2. Do the steps that the release notes name, in this order. Run each command
   in the pod, as in step 3 of [Installing the Chart](#installing-the-chart):

    ```bash
    kubectl -n imbi exec deploy/imbi -- imbi-api setup-permissions
    kubectl -n imbi exec deploy/imbi -- imbi-api setup-service-accounts
    kubectl -n imbi exec deploy/imbi -- imbi-api setup-clickhouse
    kubectl -n imbi exec deploy/imbi -- imbi-api setup-prompts
    ```

3. When the release adds an Iggy stream, restart the connectors runtime
   after `setup-clickhouse`:

    ```bash
    kubectl -n imbi rollout restart deployment/imbi-connect
    ```

See [Applying Upgrades](../getting-started/setup.md#applying-upgrades) for
what each command does.

## Uninstalling

```bash
helm uninstall imbi
```

!!! warning
    Uninstalling the chart will delete all Kubernetes resources but
    persistent volumes may remain. Delete them manually if you want
    to remove all data.
