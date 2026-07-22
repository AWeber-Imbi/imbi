# Installation

## Requirements

- Python 3.12 or higher
- PostgreSQL 16+ with [Apache AGE](https://age.apache.org/) extension (for graph features)
- ClickHouse 23.0+ (for analytics features)

## Install from PyPI

```bash
pip install imbi-common
```

## Install from Source

### For Development

```bash
# Clone the repository
git clone https://github.com/AWeber-Imbi/imbi-common.git
cd imbi-common

# Install dependencies and pre-commit hooks
just setup
```

### For Production

```bash
pip install git+https://github.com/AWeber-Imbi/imbi-common.git@main
```

## Verify Installation

```python
# Test basic imports
from imbi_common import settings, models, graph, clickhouse, auth

print("All modules imported successfully")
```

## Optional Dependencies

### Server

To use the `serve` command for running uvicorn:

```bash
pip install imbi-common[server]
```

### OpenTelemetry

To install the OpenTelemetry SDK, exporter, and instrumentation packages
at versions known to be compatible with each other:

```bash
pip install imbi-common[otel]
```

!!! important "Use the `otel` extra to pin the stack"
    Downstream packages (e.g. `imbi-api`, `imbi-gateway`, `imbi-mcp`)
    that ship OpenTelemetry support **MUST** depend on
    `imbi-common[otel]` instead of declaring individual
    `opentelemetry-*` packages.

    Downstream packages **SHOULD NOT** pin their own versions of
    `opentelemetry-api`, `opentelemetry-sdk`,
    `opentelemetry-distro`, `opentelemetry-exporter-*`, or
    `opentelemetry-instrumentation-*` packages. Pinning those
    separately defeats the purpose of the `otel` extra and reintroduces
    the version-skew problems it exists to prevent — the
    `opentelemetry-api`/`-sdk` packages (`1.x.y`) and the
    instrumentation/exporter packages (`0.x` betas) move on a coupled
    release cadence, and mismatched versions break instrumentation at
    import time.

    Installing through the `otel` extra ensures that every service in
    the Imbi ecosystem ends up with a single, consistent set of
    OpenTelemetry package versions resolved by the consumer's package
    manager.

The `otel` extra only installs the packages — it does **not**
configure OpenTelemetry. Library users (i.e. the application or
service that depends on `imbi-common[otel]`) are responsible for:

- Configuring the OTLP exporter via the standard environment
  variables documented at
  <https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/>
  (e.g. `OTEL_EXPORTER_OTLP_ENDPOINT`,
  `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_EXPORTER_OTLP_PROTOCOL`).
- Configuring the OpenTelemetry SDK via the standard environment
  variables documented at
  <https://opentelemetry.io/docs/languages/sdk-configuration/general/>
  (e.g. `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`,
  `OTEL_TRACES_SAMPLER`, `OTEL_SDK_DISABLED`).

At a minimum, library users should set `OTEL_SERVICE_NAME` and
include `service.version=<version>` in `OTEL_RESOURCE_ATTRIBUTES` so
that traces, metrics, and logs can be attributed to a specific
service and release:

```bash
export OTEL_SERVICE_NAME=imbi-api
export OTEL_RESOURCE_ATTRIBUTES="service.version=2.5.5"
```

`OTEL_RESOURCE_ATTRIBUTES` is a comma-separated list of `key=value`
pairs, so additional attributes (e.g. `deployment.environment`) can
be appended:

```bash
export OTEL_RESOURCE_ATTRIBUTES="service.version=2.5.5,deployment.environment=production"
```

The bundled `opentelemetry-sdk` also ships entry-point-registered
resource detectors that can enrich the resource with process, OS,
and host attributes without any code changes. Opt in by listing
their names (or `*` for all of them) in
`OTEL_EXPERIMENTAL_RESOURCE_DETECTORS`:

```bash
export OTEL_EXPERIMENTAL_RESOURCE_DETECTORS=process,os,host
```

The `otel` detector — which reads `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES` — is always active and does not need to
be listed. Third-party detector packages (cloud-provider, Kubernetes,
container, etc.) self-register on install via the
`opentelemetry_resource_detector` entry-point group and only need to
be added to `OTEL_EXPERIMENTAL_RESOURCE_DETECTORS` to take effect.

### Documentation

To build documentation locally:

```bash
pip install imbi-common[docs]
mkdocs serve
```

Visit `http://localhost:8000` to view the documentation.

## Database Setup

### PostgreSQL with Apache AGE

imbi-common uses PostgreSQL with the Apache AGE graph extension. The
recommended approach for local development is the bundled Docker Compose
setup (via `just docker`), which starts a pre-configured PostgreSQL image
with AGE, pgvector, pg_cron, and pgtap already installed.

```bash
# Using the project's compose setup
just docker
```

Or run the custom image manually:

```bash
docker run -d \
  --name postgres-age \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=secret \
  ghcr.io/aweber-imbi/postgres:latest
```

### ClickHouse

```bash
# Using Docker
docker run -d \
  --name clickhouse \
  -p 8123:8123 -p 9000:9000 \
  clickhouse/clickhouse-server:latest
```

## Configuration

Create a configuration file:

```toml
# config.toml

[postgres]
url = "postgresql://postgres:secret@localhost:5432/imbi"

[clickhouse]
url = "clickhouse+http://localhost:8123"

[auth]
jwt_secret = "your-secret-key-here"
```

Or use environment variables:

```bash
export POSTGRES_URL="postgresql://postgres:secret@localhost:5432/imbi"
export CLICKHOUSE_URL="clickhouse+http://localhost:8123"
export IMBI_AUTH_JWT_SECRET="your-secret-key-here"
```

## Next Steps

- [Quick Start Guide](quickstart.md)
- [Configuration Reference](configuration.md)
- [Database Setup Guide](guides/database-setup.md)
