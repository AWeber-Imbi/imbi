# Installation

Imbi is distributed as a Docker image that packages all services together.

## Prerequisites

- Docker 24+ with Docker Compose v2, or a Kubernetes cluster with Helm
- PostgreSQL with the Apache AGE extension (the `ghcr.io/aweber-imbi/postgres`
  image bundles AGE, pg_cron, and pgvector)
- ClickHouse 24+
- Apache Iggy (`ghcr.io/aweber-imbi/iggy`). Every ClickHouse write goes
  through Iggy. The connectors runtime from the same image moves the
  messages into ClickHouse.
- Valkey. Without it, imbi-api starts, but its background workers (commit,
  pull request, and deployment sync, release promotion, maintenance, and the
  sweepers) do not start.
- S3-compatible storage for uploads. imbi-api creates the bucket at startup.
- An SMTP server. Email is on by default. To turn it off, set
  `IMBI_EMAIL_ENABLED=false`.

Agent runners use a separate image and chart. See
[Agent Runners](../deployment/agent-runners.md).

## Docker

The image is published to the GitHub Container Registry and to Docker Hub as
`aweber/imbi`. Each release has a version tag and moves `latest`. Use a
version tag for a production install.

```bash
docker pull ghcr.io/aweber-imbi/imbi:latest
```

## Docker Compose

This Compose file runs Imbi and all of its dependencies on one host. It is
for evaluation, not for production.

Use image 2.39.1 or later. On a new install, 2.39.0 cannot create its Iggy
topics, and imbi-api exits at startup (see
[issue #469](https://github.com/AWeber-Imbi/imbi/issues/469)).

1. Create a directory, and in it create `compose.yaml`:

    ```yaml
    services:
      imbi:
        image: ghcr.io/aweber-imbi/imbi:latest
        ports:
          - "8080:8080"
        env_file: .env
        environment:
          ENVIRONMENT: production
          IMBI_API_URL: http://localhost:8080/api
          VITE_API_URL: http://localhost:8080/api
          CLICKHOUSE_URL: clickhouse+http://default:password@clickhouse:8123/imbi
          POSTGRES_URL: postgresql://postgres:secret@postgres/imbi
          IGGY_URL: iggy+tcp://iggy:iggy@iggy:8090
          IMBI_IGGY_CONNECTORS_API_KEYS: change-me-connectors-key
          VALKEY_URL: valkey://valkey:6379/0
          S3_ENDPOINT_URL: http://ministack:4566
          S3_ACCESS_KEY: test
          S3_SECRET_KEY: test
          IMBI_EMAIL_SMTP_HOST: mailpit
          IMBI_EMAIL_SMTP_PORT: "1025"
          IMBI_EMAIL_SMTP_USE_TLS: "false"
        depends_on:
          clickhouse:
            condition: service_healthy
          iggy:
            condition: service_healthy
          mailpit:
            condition: service_healthy
          ministack:
            condition: service_healthy
          postgres:
            condition: service_healthy
          valkey:
            condition: service_healthy

      iggy-connect:
        image: ghcr.io/aweber-imbi/iggy:0.9.0-edge.6-0
        environment:
          IGGY_MODE: connectors
          IGGY_CONNECTORS_CONNECTORS_BASE_URL: http://imbi:8000/api/iggy/connectors
          IGGY_CONNECTORS_API_KEY: change-me-connectors-key
          IGGY_CONNECTORS_IGGY_ADDRESS: iggy:8090
          IGGY_CONNECTORS_IGGY_USERNAME: iggy
          IGGY_CONNECTORS_IGGY_PASSWORD: iggy
        restart: on-failure
        depends_on:
          iggy:
            condition: service_healthy
          imbi:
            condition: service_started

      clickhouse:
        image: clickhouse/clickhouse-server:latest
        environment:
          CLICKHOUSE_USER: default
          CLICKHOUSE_PASSWORD: password
          CLICKHOUSE_DB: imbi
        healthcheck:
          test: ["CMD-SHELL", "clickhouse client -q 'SELECT 1'"]
          interval: 5s
          timeout: 5s
          retries: 10

      iggy:
        image: ghcr.io/aweber-imbi/iggy:0.9.0-edge.6-0
        environment:
          IGGY_ROOT_USERNAME: iggy
          IGGY_ROOT_PASSWORD: iggy
          IGGY_TCP_ENABLED: true
          IGGY_TCP_ADDRESS: 0.0.0.0:8090
          IGGY_HTTP_ENABLED: true
          IGGY_HTTP_ADDRESS: 0.0.0.0:3000
          IGGY_SYSTEM_SHARDING_PIN_CORES: "false"
        cap_add:
          - SYS_NICE
        security_opt:
          - seccomp:unconfined
        ulimits:
          memlock:
            soft: -1
            hard: -1
        healthcheck:
          test: ["CMD", "iggy", "ping"]
          start_period: 15s
          start_interval: 2s
          interval: 60s
          timeout: 5s
          retries: 10

      mailpit:
        image: axllent/mailpit:v1.21.5
        ports:
          - "8025:8025"
        environment:
          MP_SMTP_AUTH_ACCEPT_ANY: 1
          MP_SMTP_AUTH_ALLOW_INSECURE: 1
        healthcheck:
          test: ["CMD", "wget", "-qO-", "http://localhost:8025/api/v1/info"]
          interval: 5s
          timeout: 5s
          retries: 10

      ministack:
        image: ministackorg/ministack
        environment:
          SERVICES: s3
        healthcheck:
          test:
            [
              "CMD",
              "python",
              "-c",
              "import urllib.request; urllib.request.urlopen('http://localhost:4566/_ministack/health')",
            ]
          interval: 5s
          timeout: 5s
          retries: 10
          start_period: 30s

      postgres:
        image: ghcr.io/aweber-imbi/postgres:latest
        environment:
          POSTGRES_PASSWORD: secret
          POSTGRES_DB: imbi
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U postgres"]
          interval: 5s
          timeout: 5s
          retries: 10

      valkey:
        image: valkey/valkey:8-alpine
        healthcheck:
          test: ["CMD-SHELL", "valkey-cli ping"]
          interval: 5s
          timeout: 5s
          retries: 10
    ```

2. Generate the three secrets into `.env`:

    ```bash
    docker run --rm ghcr.io/aweber-imbi/imbi:latest python3 -c "import secrets; from cryptography.fernet import Fernet; print('IMBI_AUTH_JWT_SECRET=' + secrets.token_urlsafe(32)); print('IMBI_AUTH_ENCRYPTION_KEY=' + Fernet.generate_key().decode()); print('IMBI_CONFIG_ENCRYPTION_KEY=' + Fernet.generate_key().decode())" > .env
    ```

3. Create the PostgreSQL schema. This command also starts the dependencies:

    ```bash
    docker compose run --rm imbi imbi-api setup-postgres
    ```

    From 2.39.1, this step is optional: `setup` creates the schema itself.

4. Run the interactive setup. See [Initial Setup](setup.md) for the prompts:

    ```bash
    docker compose run --rm imbi setup
    ```

5. Start Imbi:

    ```bash
    docker compose up -d
    ```

6. Open `http://localhost:8080` and log in with the admin user from step 4.
   Mailpit shows the email that Imbi sends at `http://localhost:8025`.

### Why these values

- `ENVIRONMENT: production` makes Imbi refuse to start without
  `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, and
  `IMBI_CONFIG_ENCRYPTION_KEY`. When `ENVIRONMENT` is unset, its value is
  `development`, and each process generates the keys that are not set. Then
  one service in the container cannot decrypt a value that another service
  encrypted, and no encrypted value is usable after a restart.
- `IMBI_API_URL` is the public URL of the API. imbi-api mounts its routes
  under the path of this URL. The bundled Caddy sends `/api/*` to imbi-api
  and keeps the prefix. Without `/api` in this URL, every API call through
  Caddy gets a 404.
- `VITE_API_URL` is the same URL for the UI. Caddy writes it into
  `index.html`. Without it, the UI does not load.
- `IMBI_IGGY_CONNECTORS_API_KEYS` on `imbi` and `IGGY_CONNECTORS_API_KEY` on
  `iggy-connect` must have the same value. iggy-connect uses the key to get
  its sink configuration from imbi-api. It connects to imbi-api on port 8000
  directly, not through Caddy.
- You do not have to set the internal service account credentials. In this
  mode the container makes and seeds them each time it starts.

## Kubernetes

See the [Kubernetes deployment guide](../deployment/kubernetes.md) for
deploying with the Helm chart. The chart runs Imbi in production mode by
default, so it refuses to render without `auth.jwtSecret`,
`auth.encryptionKey`, and `auth.configEncryptionKey`.

## Next Steps

See [Configuration](configuration.md) for the other settings, and
[Initial Setup](setup.md) for what the setup command does.
