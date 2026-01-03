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

## Services Using imbi-common

- **imbi-api**: Main API service for service management
- **imbi-gateway**: Webhook processing service
- **imbi-mcp**: Model Context Protocol server for Claude integration

## Documentation

Full documentation is available at: [https://aweber-imbi.github.io/imbi-common/](https://aweber-imbi.github.io/imbi-common/)

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/AWeber-Imbi/imbi-common.git
cd imbi-common

# Install with development dependencies
./bootstrap
```

### Running Tests

```bash
uv run pytest
```

### Code Quality

```bash
pre-commit run --all-files
```

## License

BSD-3-Clause - See [LICENSE](LICENSE) file for details.

## Authors

- Gavin M. Roy <gavinr@aweber.com>

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
