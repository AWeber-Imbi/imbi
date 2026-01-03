# Imbi Common Library

Shared library for the Imbi ecosystem providing core data access, authentication primitives, and domain models.

## Overview

`imbi-common` is a Python library that provides common functionality for all Imbi services including:

- **Database Clients**: Neo4j (graph database) and ClickHouse (analytics database) with connection management
- **Domain Models**: Pydantic models for Projects, Users, Organizations, Teams, and more
- **Authentication**: Password hashing (Argon2), JWT token creation/verification, token encryption
- **Configuration**: Pydantic Settings-based configuration management with TOML file support
- **Blueprint System**: Dynamic schema extension system for runtime model customization
- **Logging**: Consistent logging configuration across all services

## Installation

```bash
pip install imbi-common
```

## Quick Start

### Configuration

```python
from imbi_common import settings

# Load configuration from TOML file or environment variables
config = settings.load_config()

# Access individual settings
neo4j_config = settings.Neo4j()
clickhouse_config = settings.Clickhouse()
auth_config = settings.Auth()
```

### Database Access

```python
from imbi_common import neo4j, clickhouse, models

# Initialize database connections
await neo4j.initialize()
await clickhouse.initialize()

# Create a project in Neo4j
project = models.Project(
    name="My Service",
    slug="my-service",
    description="A sample service"
)
await neo4j.create_node(project)

# Query projects
async for project in neo4j.fetch_nodes(models.Project, order_by="name"):
    print(f"Project: {project.name}")

# Insert analytics data to ClickHouse
await clickhouse.insert("session_activity", [activity_data])
```

### Authentication

```python
from imbi_common.auth import core

# Hash a password
password_hash = core.hash_password("secure_password")

# Verify password
if core.verify_password("secure_password", password_hash):
    print("Password verified!")

# Create JWT token
token = core.create_access_token(
    subject="user@example.com",
    extra_claims={"role": "admin"}
)

# Verify and decode JWT
payload = core.verify_token(token)
```

### Logging

```python
from imbi_common import logging

# Configure logging (call once at application startup)
logging.configure_logging(dev=True)  # Sets DEBUG level for imbi loggers

# Or provide custom config
custom_config = {
    "version": 1,
    "handlers": {...},
    "loggers": {...}
}
logging.configure_logging(config=custom_config)
```

## Services Using imbi-common

- **imbi-api**: Main API service for service management
- **imbi-mcp**: Model Context Protocol server for Claude integration
- **imbi-webhooks**: Webhook processing service

## Documentation

Full documentation is available at: [https://your-org.github.io/imbi-common/](https://your-org.github.io/imbi-common/)

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/your-org/imbi-common.git
cd imbi-common

# Install with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run unit tests (no database required)
python -m unittest discover tests

# Run all tests including integration tests (requires Docker)
python -m unittest discover tests

# Skip integration tests
export SKIP_INTEGRATION_TESTS=1
python -m unittest discover tests
```

### Code Quality

```bash
# Run linting
ruff check src tests

# Run formatting
ruff format src tests

# Run type checking
mypy src
```

## License

BSD-3-Clause - See [LICENSE](LICENSE) file for details.

## Authors

- Gavin M. Roy <gavinr@aweber.com>

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
