# Installation

## Requirements

- Python 3.12 or higher
- Neo4j 5.0+ (for graph database features)
- ClickHouse 23.0+ (for analytics features)

## Install from PyPI

```bash
pip install imbi-common
```

## Install from Source

### For Development

```bash
# Clone the repository
git clone https://github.com/aweber/imbi-common.git
cd imbi-common

# Install with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### For Production

```bash
pip install git+https://github.com/aweber/imbi-common.git@main
```

## Verify Installation

```python
import imbi_common

print(f"imbi-common version: {imbi_common.__version__}")

# Test basic imports
from imbi_common import settings, models, neo4j, clickhouse, auth

print("✓ All modules imported successfully")
```

## Optional Dependencies

### Documentation

To build documentation locally:

```bash
pip install imbi-common[docs]
mkdocs serve
```

Visit `http://localhost:8000` to view the documentation.

## Database Setup

### Neo4j

```bash
# Using Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5-community
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

[neo4j]
url = "neo4j://localhost:7687"
user = "neo4j"
password = "password"

[clickhouse]
url = "http://localhost:8123"

[auth]
jwt_secret = "your-secret-key-here"
```

Or use environment variables:

```bash
export NEO4J_URL="neo4j://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
export CLICKHOUSE_URL="http://localhost:8123"
export IMBI_AUTH_JWT_SECRET="your-secret-key-here"
```

## Next Steps

- [Quick Start Guide](quickstart.md)
- [Configuration Reference](configuration.md)
- [Database Setup Guide](guides/database-setup.md)
