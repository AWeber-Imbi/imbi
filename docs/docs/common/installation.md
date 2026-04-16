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
