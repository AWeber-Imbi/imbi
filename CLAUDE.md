# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Import Style Rules

**CRITICAL**: Follow these import rules strictly for all Python code:

### Rule 1: Import modules, not classes/functions

**Correct:**
```python
import datetime
result = datetime.datetime.now()
```

**Incorrect:**
```python
from datetime import datetime
result = datetime.now()
```

### Rule 2: Submodules use `from` imports

**Correct:**
```python
from unittest import mock
mock.patch()

from piccolo import columns, table
columns.Text()
```

**Incorrect:**
```python
import unittest.mock
unittest.mock.patch()

import piccolo.columns
piccolo.columns.Text()
```

### Rule 3: Local module imports (not from imports)

**Correct:**
```python
import imbi.models.base
class MyModel(imbi.models.base.AuditedTable):
    pass
```

**Incorrect:**
```python
from imbi.models.base import AuditedTable
class MyModel(AuditedTable):
    pass
```

### Import Ordering

1. `__future__` imports
2. Standard library imports
3. Third-party imports
4. Local/project imports

Each group separated by a blank line.

## Repository Structure

Imbi is a DevOps Service Management Platform with a multi-repository architecture using Git submodules:

- **api/** - Python backend (Tornado/sprockets-postgres) - submodule from imbi-api
- **ui/** - React frontend (webpack, Tailwind CSS) - submodule from imbi-ui
- **ddl/** - PostgreSQL database schema (pgTAP tests) - submodule from imbi-schema
- **openapi/** - OpenAPI specification - submodule from imbi-openapi

**CRITICAL**: Always run `git submodule update --init --recursive` after cloning or when submodules are missing.

## Development Setup

### Initial Setup
```bash
# Initialize all submodules
git submodule update --init --recursive

# Setup the entire project (api, openapi, ui)
make setup

# Or setup individual components
cd api && make setup  # Creates Python venv, installs deps, runs bootstrap
cd ui && yarn install
cd openapi && yarn install
```

### Running Locally
```bash
# Terminal 1: Start UI dev server (webpack-dev-server with hot reload)
cd ui
yarn serve  # Runs on http://localhost:8080

# Terminal 2: Start API server
cd api
source env/bin/activate
imbi --debug build/debug.yaml  # Runs on http://localhost:8000
```

Default credentials: username `test`, password `password`

### Docker Development Environment

The `api/bootstrap` script initializes Docker Compose services and generates configuration:
- **postgres** - PostgreSQL with Imbi schema (aweber/imbi-postgres:latest)
- **ldap** - OpenLDAP for authentication
- **opensearch** - Search backend
- **redis** - Session and stats storage

Running `api/bootstrap` creates:
- `api/.env` - Environment variables for service ports
- `api/build/debug.yaml` - Development configuration
- `api/build/test.yaml` - Test configuration

## Common Development Commands

### Python API (from api/)
```bash
# Run all tests (lint + coverage)
make test

# Run linting only (pre-commit hooks: bandit, flake8, yapf)
make lint

# Run tests with coverage
make coverage

# Run a single test file
source env/bin/activate
python -m unittest tests.test_user

# Run a specific test
python -m unittest tests.test_user.TestClass.test_method

# Apply code formatting
env/bin/pre-commit run yapf --all-files

# Check security issues
env/bin/pre-commit run bandit --all-files
```

### UI (from ui/)
```bash
# Run all UI tests (eslint, prettier, depcheck, jest)
yarn test

# Run linting only
yarn eslint

# Format code
yarn prettier

# Check formatting without changes
yarn prettier-check

# Build production bundle
NODE_ENV=production yarn build
```

### Database (from ddl/)
```bash
# Run DDL tests (pgTAP)
make test

# Bootstrap DDL environment
make bootstrap
```

### Full Distribution Build (from root)
```bash
# Builds OpenAPI docs, UI bundle, and Python package
make dist
```

## Architecture Overview

### Backend (Python/Tornado)

**Core Framework:**
- Tornado async web framework
- sprockets-postgres for async PostgreSQL connections with connection pooling
- sprockets.http for application scaffolding
- tornado-openapi3 for API validation

**Authentication:**
- Multi-provider: LDAP (ldap3), Google OAuth2, local users
- Session management via Redis (aioredis)
- Permission-based access control defined in `permissions.py`

**Endpoint Pattern:**
All endpoints inherit from base classes in `api/imbi/endpoints/base.py`:
- `CRUDRequestHandler` - Full CRUD operations
- `CollectionRequestHandler` - List/Create operations
- `RecordRequestHandler` - Get/Update/Delete single records

Endpoints define SQL queries as class attributes:
- `GET_SQL` - Fetch single record
- `COLLECTION_SQL` - Fetch collection (supports {{WHERE}} and {{ORDER_BY}} placeholders)
- `POST_SQL`, `PATCH_SQL`, `DELETE_SQL` - Mutation operations
- `FIELDS` - List of allowed fields for the endpoint
- `TTL` - Cache timeout

**Search:**
OpenSearch integration for project and operations log search (`api/imbi/opensearch/`)

**Automations:**
External integrations in `api/imbi/automations/`:
- GitHub, GitLab, Sentry, SonarQube, PagerDuty
- Triggered by project lifecycle events

### Frontend (React)

**Structure:**
- `ui/src/js/views/` - Page components organized by feature
- `ui/src/js/components/` - Reusable React components
- `ui/src/js/schema/` - JSON schemas for forms and validation
- `ui/src/js/state.jsx` - Global state management (React Context)

**Styling:**
- Tailwind CSS for utility classes
- Custom theme in `ui/src/js/theme.js`
- FontAwesome icons via `@fortawesome/react-fontawesome`

**Build:**
- Webpack for bundling (configs: webpack.dev.js, webpack.production.js)
- Babel for JSX/ES6+ transpilation
- Hot module replacement in dev mode

### Database

**Schema Management:**
- All schema in `ddl/` with MANIFEST file defining load order
- Versioned in `v1` schema
- pgTAP tests in `ddl/tests/`
- Database functions for computed values (e.g., `v1.project_score()`)

**Key Concepts:**
- Projects are the central entity (namespaced, typed, scored)
- Facts: typed key-value metadata for projects
- Components: Software inventory (SBOM) tracking
- Operations Log: Deployment and incident history
- Integrations: OAuth2 connections to external services

## Configuration

Configuration is YAML-based (see `example.yaml`):
- `http` - Server settings (port, processes, xheaders)
- `postgres` - Database connection (URL, pool settings, timeouts)
- `ldap` - LDAP authentication settings
- `session` - Redis session configuration
- `stats` - Redis stats configuration
- `opensearch` - Search backend settings
- `logging` - Python dictConfig format

## Testing Strategy

**Python:**
- Unit tests in `api/tests/` mirroring `api/imbi/` structure
- Tests use unittest framework
- Coverage target tracked via coverage.py
- Security scanning with bandit
- Style enforcement via flake8 + yapf

**JavaScript:**
- Jest for unit tests
- ESLint for linting (react, react-hooks plugins)
- Prettier for formatting
- Husky pre-commit hooks for automated checks

**Database:**
- pgTAP for DDL testing
- plpgsql_check for function validation

## Code Style

**Python:**
- Strict PEP-8 compliance
- Import order: pycharm style (stdlib, third-party, local)
- YAPF formatting with specific config in setup.cfg
- Docstrings for public modules/classes (RST format)

**JavaScript:**
- Prettier with default config
- ESLint rules for React best practices
- Functional components with hooks preferred

## Release Process

1. Update VERSION file in `api/`
2. Update submodules: `git submodule update --remote --merge`
3. Commit: `git commit -m 'Release version X.Y.Z' -a`
4. Tag: `git tag X.Y.Z && git push origin X.Y.Z`
5. GitHub Actions handles: UI build → Python package → PyPI → Docker Hub

## Important Notes

- **Submodules**: The main repo is primarily a coordination point; most code lives in submodules
- **Database First**: Schema changes in ddl/ must be tagged before API changes
- **OpenAPI**: Spec is built from openapi/ and bundled into the API at build time
- **Session Management**: Redis-backed sessions with configurable TTL
- **CORS**: Configurable CORS support for cross-origin API access
- **Stats**: Real-time metrics via Redis and periodic aggregation
