# Imbi Helm Chart

Helm chart for deploying Imbi to Kubernetes.

## Databases

This chart does **not** bundle any database subcharts. Provision both
datastores externally and point the chart at them via `values.yaml`:

| Datastore | Recommended approach | Value |
|-----------|----------------------|-------|
| PostgreSQL + Apache AGE | [CloudNativePG](https://cloudnative-pg.io/) cluster with an AGE-enabled image | `externalPostgresql.url` |
| ClickHouse | [Altinity ClickHouse operator](https://github.com/Altinity/clickhouse-operator) | `externalClickhouse.url` |

See [the Kubernetes deployment guide](../../docs/deployment/kubernetes.md)
for operator setup and an example CloudNativePG `Cluster` manifest.

## Install

```bash
helm install imbi helm/imbi \
  --set auth.jwtSecret=your-secret \
  --set auth.encryptionKey=your-key \
  --set externalPostgresql.url=postgresql://imbi:password@imbi-pg-rw:5432/imbi \
  --set externalClickhouse.url=clickhouse+http://default:password@clickhouse-imbi:8123/imbi
```

See `values.yaml` for all configuration options.
