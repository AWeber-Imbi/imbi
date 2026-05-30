# Imbi Helm Chart

Helm chart for deploying Imbi to Kubernetes.

## Dependencies

This chart includes the following subcharts:

| Dependency | Repository | Purpose |
|------------|------------|---------|
| ClickHouse | https://charts.bitnami.com/bitnami | Analytics database |
| PostgreSQL | https://charts.bitnami.com/bitnami | Graph + relational database (Apache AGE) |

Each can be disabled in favor of external instances via `values.yaml`.

## Install

```bash
helm dependency update helm/imbi
helm install imbi helm/imbi \
  --set auth.jwtSecret=your-secret \
  --set auth.encryptionKey=your-key
```

See `values.yaml` for all configuration options.
