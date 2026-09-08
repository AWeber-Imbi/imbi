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

## Installing the Chart

```bash
helm install imbi helm/imbi \
  --set auth.jwtSecret=your-secret \
  --set auth.encryptionKey=your-key
```

## Configuration

### Required Values

```yaml
auth:
  jwtSecret: "your-jwt-secret"
  encryptionKey: "your-encryption-key"
```

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
  mode: api        # or assistant, gateway, mcp, scheduler, slackbot
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
```

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
  internalApiUrl: http://imbi-api.imbi.svc.cluster.local:8000
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

```bash
helm upgrade imbi helm/imbi
```

## Uninstalling

```bash
helm uninstall imbi
```

!!! warning
    Uninstalling the chart will delete all Kubernetes resources but
    persistent volumes may remain. Delete them manually if you want
    to remove all data.
