# Installation

Imbi is distributed as a Docker image that packages all services together.

## Prerequisites

- Docker 24+ or a Kubernetes cluster with Helm
- PostgreSQL with the Apache AGE extension (the `ghcr.io/aweber-imbi/postgres`
  image bundles AGE, pg_cron, and pgvector)
- ClickHouse 24+

## Docker

Pull the latest image:

```bash
docker pull ghcr.io/aweber-imbi/imbi:latest
```

## Docker Compose

Create a `compose.yaml` to run Imbi with all dependencies:

```yaml
services:
  imbi:
    image: ghcr.io/aweber-imbi/imbi:latest
    ports:
      - "8080:8080"
    environment:
      CLICKHOUSE_URL: clickhouse+http://default:password@clickhouse:8123/imbi
      POSTGRES_URL: postgresql://postgres:secret@postgres/imbi
      IMBI_AUTH_JWT_SECRET: change-me-to-a-random-secret
      IMBI_AUTH_ENCRYPTION_KEY: change-me-to-a-fernet-key
    depends_on:
      clickhouse:
        condition: service_healthy
      postgres:
        condition: service_healthy

  clickhouse:
    image: clickhouse/clickhouse-server:latest
    ports:
      - "8123:8123"
    environment:
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: password
      CLICKHOUSE_DB: imbi
    healthcheck:
      test: ["CMD-SHELL", "clickhouse client -q 'SELECT 1'"]
      interval: 5s
      timeout: 5s
      retries: 10

  postgres:
    image: ghcr.io/aweber-imbi/postgres:latest
    ports:
      - "5432:5432"
    environment:
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: imbi
    healthcheck:
      test: ["CMD-SHELL", "pg_isready"]
      interval: 5s
      timeout: 5s
      retries: 10
```

Start everything:

```bash
docker compose up -d
```

## Kubernetes

See the [Kubernetes deployment guide](../deployment/kubernetes.md) for
deploying with the Helm chart.

## Next Steps

After installation, proceed to [Configuration](configuration.md) and then
[Initial Setup](setup.md) to create your admin user.
