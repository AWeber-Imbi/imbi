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

- **`ENVIRONMENT` and `IMBI_CONFIG_ENCRYPTION_KEY`.** The chart value
  `auth.encryptionKey` sets `IMBI_AUTH_ENCRYPTION_KEY`, not
  `IMBI_CONFIG_ENCRYPTION_KEY`. These are two different keys. Every chart
  install runs with `ENVIRONMENT` unset, which is `development`. Each process then
  generates its own configuration encryption key. Encrypted configuration
  values, such as AI provider keys, cannot be decrypted after a restart or by
  another process.
- **`VALKEY_URL`.** imbi-api starts without Valkey, but its background
  workers (commit, pull request, and deployment sync, release promotion,
  maintenance, and the sweepers) do not start.
- **`VITE_API_URL`.** The UI reads the API URL from this variable. Without
  it, the UI does not load in `all` and `ui` mode.
- **Other variables.** The chart has no `extraEnv` or `extraEnvFrom` value.
  It cannot set, for example, `IMBI_UI_URL`, the `IMBI_INTERNAL_*_URL`
  values of the **System health** card, CORS, MCP OAuth, Sentry, SMTP
  authentication, or the Slack tokens. Thus `service.mode: slackbot` cannot
  start.
- **`ANTHROPIC_API_KEY` from `existingSecret`.** The chart sets
  `ANTHROPIC_API_KEY` only when `assistant.enabled` is true and
  `assistant.anthropicApiKey` has a value. With `existingSecret` and no
  `assistant.anthropicApiKey`, the chart does not read the
  `anthropic-api-key` key.

## Installing the Chart

Use image 2.39.1 or later. On a new install, 2.39.0 cannot create its Iggy
topics, and imbi-api exits at startup (see
[issue #469](https://github.com/AWeber-Imbi/imbi/issues/469)).

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

    The secrets and passwords above are placeholders. Replace them with your
    own values.

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
    nothing when imbi-api has already created the schema. From 2.39.1, it is
    optional: `setup` creates the schema itself.

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

Set `image.tag` to a release version in production. The default is
`latest`. The chart `appVersion` is not the Imbi version, so the
`app.kubernetes.io/version` label does not show the version that runs.

`replicaCount` sets the number of pods in `all` mode. `resources` sets the
requests and limits of the Imbi container.

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

Set `service.internalApiUrl` to the imbi-api Service in every mode other
than `all` and `api`. The chart refuses to render in `gateway`,
`scheduler`, and `workflows` mode when `internalApiUrl` is the loopback
default. In `scheduler` and `workflows` mode, it also refuses to render
when `service.publicApiUrl` is empty.

### Scheduler

The scheduler runs every task as its own service account, `imbi-scheduler`.
`imbi-api setup` (or `imbi-api setup-service-accounts`) seeds the account and
its client credential with the values below. Invent the values. When you
leave them empty, setup makes a pair and prints it one time. Set both values
or neither. In `all` mode, the container seeds a credential at startup when
both values are empty.

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
reports healthy while every `api`-target firing fails. It also refuses to
render when `publicApiUrl` is empty. More than one replica is
safe: due firings are claimed with `FOR UPDATE SKIP LOCKED`, so replicas take
disjoint claims. See
[Scheduler configuration](../scheduler/configuration.md).

Using `existingSecret`, the scheduler reads the optional
`scheduler-sa-client-id` and `scheduler-sa-client-secret` keys from it.

### Existing secret

Set `existingSecret` to the name of a Secret that you manage. The chart then
does not make its own Secret, and reads these keys:

| Key | Variable | When the chart reads it |
|---|---|---|
| `jwt-secret` | `IMBI_AUTH_JWT_SECRET` | Always |
| `encryption-key` | `IMBI_AUTH_ENCRYPTION_KEY` | Always |
| `clickhouse-url` | `CLICKHOUSE_URL` | Always |
| `iggy-url` | `IGGY_URL` | Always |
| `postgres-url` | `POSTGRES_URL` | Always |
| `iggy-connectors-api-key` | `IMBI_IGGY_CONNECTORS_API_KEYS`, `IGGY_CONNECTORS_API_KEY` | Optional for imbi-api. Required by the connectors runtime |
| `iggy-password` | `IGGY_CONNECTORS_IGGY_PASSWORD` | When `iggyConnect.enabled` |
| `anthropic-api-key` | `ANTHROPIC_API_KEY` | When `assistant.enabled` and `assistant.anthropicApiKey` are set |
| `scheduler-sa-client-id`, `scheduler-sa-client-secret` | `IMBI_SCHEDULER_SA_CLIENT_*` | Optional |
| `workflows-sa-client-id`, `workflows-sa-client-secret` | `IMBI_WORKFLOWS_SA_CLIENT_*` | Optional |
| `gateway-sa-token` | `IMBI_GATEWAY_API_TOKEN` | Optional |
| `s3-access-key`, `s3-secret-key` | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | When `storage.accessKey` and `storage.secretKey` are set |

The Secret must have the keys that the chart reads. A missing key that is
not optional stops the pod. In `scheduler` and `workflows` mode, the
container does not start without its two service account keys.

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
      postInitApplicationSQL:
        - CREATE EXTENSION IF NOT EXISTS age
        - CREATE EXTENSION IF NOT EXISTS pg_cron
        - CREATE EXTENSION IF NOT EXISTS vector
  storage:
    size: 20Gi
```

CloudNativePG exposes the primary at `<cluster-name>-rw` (here `imbi-pg-rw`)
and stores the generated `imbi` user's password in the `imbi-pg-app` secret.
Use those to build `externalPostgresql.url`.

imbi-api runs `CREATE EXTENSION IF NOT EXISTS` for `age`, `pg_cron`, and
`vector` at startup. The `imbi` owner is not a superuser, so create the
extensions in the application database during bootstrap.
`postInitApplicationSQL` runs in the application database. `postInitSQL`
runs in the `postgres` database.

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

Keep the Iggy data directory on a persistent volume, and change the root
credentials. See [Operations: Apache Iggy](operations.md#apache-iggy).

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
`/metrics` on their own port (8000, 8003 and 8005). The chart adds the
`prometheus.io/scrape`, `prometheus.io/port` and `prometheus.io/path` pod
annotations in `api`, `gateway` and `scheduler` mode. In `all` mode the three
services share one pod, and the annotations name imbi-api on port 8000 only,
so the gateway and scheduler counters are not scraped. The connectors runtime
pod is annotated for its own metrics on port 8081. The `workflows` mode pod
has no metrics annotations.

For the list of metrics and the recommended alerts, see
[Operations: Metrics](operations.md#metrics).

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

1. Set `image.tag` to the new version, and upgrade the release:

    ```bash
    helm upgrade imbi helm/imbi -f values.yaml --namespace imbi
    ```

2. Do the steps in [Upgrading](upgrading.md). Run each command in the pod,
   as in step 3 of [Installing the Chart](#installing-the-chart).

## Uninstalling

```bash
helm uninstall imbi
```

!!! warning
    Uninstalling the chart will delete all Kubernetes resources but
    persistent volumes may remain. Delete them manually if you want
    to remove all data.
