# Imbi Common Library

Shared library for the Imbi ecosystem providing core data access, authentication primitives, and domain models.

## Overview

`imbi-common` is a Python library that provides common functionality for all Imbi services including:

- **Database Clients**: Apache AGE/PostgreSQL (graph database) and ClickHouse (analytics database) with connection management
- **Domain Models**: Pydantic models for Projects, Organizations, Teams, Environments, ProjectTypes, and more
- **Authentication**: JWT token creation/verification, token encryption
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

### Prerequisites

- [just](https://just.systems/man/en/packages.html) — task runner
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager

### Setup

```bash
# Clone the repository
git clone https://github.com/AWeber-Imbi/imbi-common.git
cd imbi-common

# Install dependencies and pre-commit hooks
just setup
```

### Running Tests

```bash
just test           # Full test suite with coverage (requires Docker)
just test <file>    # Run specific test file(s)
```

### Code Quality

```bash
just lint    # Run all linters
just format  # Reformat code
```

## License

BSD-3-Clause - See [LICENSE](LICENSE) file for details.

## Authors

- Dave Shawley <daves@aweber.com>
- Gavin M. Roy <gavinr@aweber.com>

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
