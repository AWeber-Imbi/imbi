# Imbi Common Library

Shared library for the Imbi ecosystem providing core data access, authentication primitives, and domain models.

## Overview

`imbi-common` is a Python library that provides common functionality for all Imbi services. It serves as the foundation for:

- **imbi-api**: Main API service for DevOps service management
- **imbi-gateway**: API gateway service
- **imbi-mcp**: Model Context Protocol server for Claude integration

## Key Features

### Database Clients

- **Apache AGE**: Graph database client (PostgreSQL + AGE extension) with connection pooling and Cypher query generation
- **ClickHouse**: Analytics database client with GDPR-compliant schema management

### Authentication

- **JWT Tokens**: Access and refresh token creation/verification
- **Token Encryption**: Fernet encryption for sensitive data at rest

### Data Models

- **Domain Models**: Projects, Organizations, Teams, Environments, ProjectTypes
- **Dynamic Schemas**: Blueprint system for runtime model extension

### Configuration

- **Pydantic Settings**: Type-safe configuration with validation
- **TOML Support**: Load configuration from files or environment variables
- **Flexible Sources**: Priority-based config loading (env > local > user > system)

### Logging

- **Consistent Format**: Unified logging across all services
- **dictConfig Support**: Standard library logging configuration
- **Development Mode**: Easy DEBUG level activation

### Server

- **Uvicorn Integration**: Reusable `serve` command for Typer-based CLIs
- **Development Mode**: Auto-reload with debug logging

## Quick Links

- [Installation Guide](installation.md)
- [Quick Start](quickstart.md)
- [Configuration Reference](configuration.md)
- [API Reference](api/settings.md)

## Architecture

The library follows a clean architecture with clear separation of concerns:

```
imbi.common/
├── settings.py      # Configuration management
├── models.py        # Domain models
├── graph/           # Apache AGE graph database client
├── clickhouse/      # Analytics database client
├── auth/            # Authentication primitives
├── blueprints.py    # Dynamic schema system
├── valkey.py        # Valkey cache client
├── logging.py       # Logging configuration
└── server.py        # Uvicorn serve command
```

## Services Using imbi-common

### imbi-api
Main API service providing RESTful endpoints for managing services, projects, teams, and infrastructure.

### imbi-gateway
API gateway service routing and authenticating requests across Imbi services.

### imbi-mcp
Model Context Protocol server that enables Claude to query and manage Imbi data through natural language.

## Support

- [GitHub Issues](https://github.com/aweber/imbi-common/issues)
- [Contributing Guide](https://github.com/aweber/imbi-common/blob/main/CONTRIBUTING.md)

## License

BSD-3-Clause - See [LICENSE](https://github.com/aweber/imbi-common/blob/main/LICENSE) for details.
