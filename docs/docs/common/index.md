# Imbi Common Library

Shared library for the Imbi ecosystem providing core data access, authentication primitives, and domain models.

## Overview

`imbi-common` is a Python library that provides common functionality for all Imbi services. It serves as the foundation for:

- **imbi-api**: Main API service for DevOps service management
- **imbi-mcp**: Model Context Protocol server for Claude integration
- **imbi-webhooks**: Webhook processing service

## Key Features

### 🗄️ Database Clients

- **Neo4j**: Graph database client with connection pooling and cypherantic integration
- **ClickHouse**: Analytics database client with GDPR-compliant schema management

### 🔐 Authentication

- **Password Security**: Argon2id hashing with automatic rehashing
- **JWT Tokens**: Access and refresh token creation/verification
- **Token Encryption**: Fernet encryption for sensitive data at rest
- **API Keys**: Programmatic access with scoped permissions

### 📊 Data Models

- **Domain Models**: Projects, Organizations, Teams, Environments, ProjectTypes
- **Auth Models**: Users, Groups, Roles, Permissions, Sessions, API Keys
- **Dynamic Schemas**: Blueprint system for runtime model extension

### ⚙️ Configuration

- **Pydantic Settings**: Type-safe configuration with validation
- **TOML Support**: Load configuration from files or environment variables
- **Flexible Sources**: Priority-based config loading (env > local > user > system)

### 📝 Logging

- **Consistent Format**: Unified logging across all services
- **dictConfig Support**: Standard library logging configuration
- **Development Mode**: Easy DEBUG level activation

## Quick Links

- [Installation Guide](installation.md)
- [Quick Start](quickstart.md)
- [Configuration Reference](configuration.md)
- [API Reference](api/settings.md)

## Architecture

The library follows a clean architecture with clear separation of concerns:

```
imbi_common/
├── settings.py      # Configuration management
├── models.py        # Domain models
├── neo4j/           # Graph database client
├── clickhouse/      # Analytics database client
├── auth/            # Authentication primitives
├── blueprints.py    # Dynamic schema system
└── logging.py       # Logging configuration
```

## Services Using imbi-common

### imbi-api
Main API service providing RESTful endpoints for managing services, projects, teams, and infrastructure.

### imbi-mcp
Model Context Protocol server that enables Claude to query and manage Imbi data through natural language.

### imbi-webhooks
Event processing service that handles webhooks from external systems and updates Imbi data.

## Support

- [GitHub Issues](https://github.com/aweber/imbi-common/issues)
- [Contributing Guide](https://github.com/aweber/imbi-common/blob/main/CONTRIBUTING.md)

## License

BSD-3-Clause - See [LICENSE](https://github.com/aweber/imbi-common/blob/main/LICENSE) for details.
