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
  --set auth.encryptionKey=your-fernet-key \
  --set auth.configEncryptionKey=another-fernet-key \
  --set externalPostgresql.url=postgresql://imbi:password@imbi-pg-rw:5432/imbi \
  --set externalClickhouse.url=clickhouse+http://default:password@clickhouse-imbi:8123/imbi \
  --set externalIggy.url=iggy+tcp://iggy:iggy@imbi-iggy:8090 \
  --set externalValkey.url=valkey://imbi-valkey:6379/0 \
  --set service.publicApiUrl=https://imbi.example.com/api \
  --set iggyConnect.apiKey=REPLACE-WITH-A-RANDOM-API-KEY \
  --set iggyConnect.iggy.address=imbi-iggy:8090 \
  --set iggyConnect.iggy.password=REPLACE-WITH-THE-IGGY-PASSWORD
```

Replace every value with your own. Make a unique random value for each
secret, and do not copy the examples above.

`environment` defaults to `production`, so the three `auth` values are
required. `extraEnv` and `extraEnvFrom` set any variable that has no chart
value.

See `values.yaml` for all configuration options.

## Scheduler

`imbi-scheduler` needs a service-account credential
(`scheduler.serviceAccount.clientId` / `clientSecret`) to run `api`-target
tasks. Running it as its own release (`service.mode: scheduler`) additionally
requires `service.internalApiUrl` and `service.publicApiUrl`; the chart fails
to render without them. See
[the scheduler configuration guide](../../docs/scheduler/configuration.md).

## Workflows

`imbi-workflows` runs workflow runs (ADR 0021). Its deploy and rollback steps
call imbi-api with a service-account credential
(`workflows.serviceAccount.clientId` / `clientSecret`). Running it as its own
release (`service.mode: workflows`) requires `service.internalApiUrl` and
`service.publicApiUrl`, as for the scheduler, and `workflows.schedulerUrl`
(for example `http://imbi-scheduler.<namespace>.svc.cluster.local:8080/api`)
for schedule triggers.
