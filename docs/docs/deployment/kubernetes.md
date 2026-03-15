# Kubernetes Deployment

Imbi provides a Helm chart for deploying to Kubernetes with all
dependencies included.

## Prerequisites

- Kubernetes 1.28+
- Helm 3.x

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

The chart includes Neo4j, ClickHouse, and PostgreSQL as dependencies.
To use external databases instead:

```yaml
neo4j:
  enabled: false
externalNeo4j:
  url: bolt://neo4j.example.com:7687

clickhouse:
  enabled: false
externalClickhouse:
  url: http://clickhouse.example.com:8123/imbi

postgresql:
  enabled: false
externalPostgresql:
  url: postgresql://user:pass@pg.example.com/imbi
```

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
