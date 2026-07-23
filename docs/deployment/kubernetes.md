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

# Scaled-out mode
service:
  mode: individual
  api:
    replicas: 3
  assistant:
    replicas: 1
  gateway:
    replicas: 2
  mcp:
    replicas: 1
```

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
