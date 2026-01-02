# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Imbi is a DevOps Service Management Platform designed to manage large environments containing many services and applications. Version 2 (currently in alpha) is a complete rewrite using FastAPI, Neo4j for graph data, and ClickHouse for analytics.

**See [README.md](README.md)** for project overview, core concepts, and full v2 roadmap including conversational AI, webhook workflows, MCP server integration, and ecosystem of services.

## Development Setup

### Package Manager

This project uses [uv](https://docs.astral.sh/uv/) for fast, reliable Python package management. Dependencies are locked in `uv.lock` for reproducible builds.

### Initial Setup
```bash
# Step 1: Bootstrap development environment
./bootstrap

# Step 2: Initialize Imbi (first time only)
uv run imbi setup
```

The `bootstrap` script:
- Syncs dependencies using `uv sync --all-extras --all-groups --locked`
- Installs pre-commit hooks via `uv run pre-commit install`
- Starts Docker Compose services (Neo4j, ClickHouse, Jaeger)
- Waits for services to be healthy (120s timeout)
- Generates `.env` file with service URLs and OpenTelemetry configuration

The `imbi setup` command (run once per instance):
- Seeds permissions and default roles (admin, developer, readonly)
- Interactively creates the initial admin user
- Idempotent: safe to run multiple times (prompts before creating duplicates)

### Environment Configuration

**Docker services** (configured in `compose.yaml`):
- **Neo4j**: ports 7474 (HTTP), 7687 (Bolt) - `NEO4J_AUTH=none`
- **ClickHouse**: ports 8123 (HTTP), 9000 (Native) - default/password
- **Jaeger**: ports 4317 (OTLP), 16686 (UI) - for OpenTelemetry tracing

The bootstrap script automatically generates a `.env` file with dynamically assigned ports and OpenTelemetry configuration. You can override settings via environment variables:

```bash
NEO4J_URL=neo4j://localhost:7687
NEO4J_USER=username
NEO4J_PASSWORD=password
```

**Neo4j URL credential extraction**: The settings model automatically extracts credentials from URLs like `neo4j://user:pass@host:7687`, URL-decodes them, and strips them from the connection URL for security. Explicit `NEO4J_USER`/`NEO4J_PASSWORD` take precedence over URL credentials.

## Common Development Commands

### Running the Application
```bash
# Run development server with auto-reload
uv run imbi run-server --dev

# Run production server (uses IMBI_ENVIRONMENT setting)
uv run imbi run-server

# Access the API
curl http://localhost:8000/status

# View Jaeger tracing UI
open http://localhost:16686
```

The server starts on `localhost:8000` by default (configurable via `IMBI_HOST` and `IMBI_PORT`). Development mode enables auto-reload when source files change.

### Code Quality
```bash
# Run all pre-commit checks (includes ruff linting + formatting)
uv run pre-commit run --all-files

# Run ruff directly
uv run ruff check .                    # Lint
uv run ruff check --fix .             # Lint with auto-fix
uv run ruff format .                   # Format code

# Run mypy type checking
uv run mypy
```

### Testing
```bash
# Run all tests with coverage (uses pytest-cov via pyproject.toml)
uv run pytest

# Run specific test file
uv run pytest tests/neo4j/test_client.py

# Run specific test class or method
uv run pytest tests/neo4j/test_client.py::Neo4jClientTestCase
uv run pytest tests/neo4j/test_client.py::Neo4jClientTestCase::test_singleton

# Run with verbose output
uv run pytest -v
```

**Coverage configuration** (`pyproject.toml`):
- Minimum coverage target: 90% (configured via `tool.coverage.report.fail_under`)
- Current coverage: ~30% (expanded functionality requires additional test coverage)
- Automatic coverage collection via `pytest --cov` (configured in `tool.pytest.ini_options.addopts`)
- XML output: `build/coverage.xml` (for Codecov)
- HTML report: `build/coverage/` (for local review)

### Docker Services
```bash
# Start services
docker compose up --wait

# Stop and clean
docker compose down --remove-orphans --volumes

# Check service status
docker compose ps

# View logs
docker compose logs -f neo4j
docker compose logs -f clickhouse
```

## Code Architecture

### High-Level Structure
- **`src/imbi/`**: Main application code
  - `app.py`: FastAPI application factory with lifespan management and auto-seeding
  - `entrypoint.py`: CLI commands (Typer-based)
  - `models.py`: Core domain models (Blueprint, User, Group, Role, Permission, Project, etc.)
  - `settings.py`: Configuration via Pydantic Settings with URL credential extraction
  - `blueprints.py`: Blueprint filtering and schema validation logic
  - `endpoints/`: API endpoint routers
    - `status.py`: Health check endpoint
    - `auth.py`: Authentication (OAuth2/OIDC, local password) and token management
    - `users.py`: User CRUD operations
    - `groups.py`: Group CRUD operations
    - `roles.py`: Role CRUD operations
    - `blueprints.py`: Blueprint CRUD operations
  - `auth/`: Authentication and authorization system
    - `core.py`: JWT token generation and password hashing
    - `oauth.py`: OAuth2/OIDC provider integration (Google, GitHub, Keycloak)
    - `permissions.py`: Permission checking and resource-based authorization
    - `seed.py`: Auto-seeding of roles and permissions
    - `models.py`: Auth-specific data models
  - `neo4j/`: Neo4j graph database integration layer
    - `client.py`: Singleton driver with event loop awareness
    - `__init__.py`: High-level API and cypherantic wrappers
    - `constants.py`: Index definitions and vector configuration
  - `clickhouse/`: ClickHouse analytics database integration
    - `client.py`: Async ClickHouse client with connection pooling
    - `__init__.py`: High-level API for queries and inserts
- **`tests/`**: Test suite with 315 tests (~30% coverage, being expanded)

### ClickHouse Integration Pattern

The ClickHouse module provides async operations for analytics and time-series data:

```python
from imbi import clickhouse

# Initialize connection (called during app startup)
await clickhouse.initialize()

# Insert Pydantic models
from imbi.models import SomeModel
data = [SomeModel(...), SomeModel(...)]
result = await clickhouse.insert('table_name', data)

# Query with parameters
results = await clickhouse.query(
    'SELECT * FROM table WHERE column = {param:String}',
    parameters={'param': 'value'}
)

# Cleanup (called during app shutdown)
await clickhouse.aclose()
```

**Implementation details** (`src/imbi/clickhouse/client.py`):
- Singleton pattern with async connection management
- Automatic Pydantic model serialization for inserts
- Support for nested/complex types via flattening
- Connection pooling and health checks

### Neo4j Integration Pattern

The Neo4j module uses a **singleton pattern with event loop awareness**:

```python
from imbi import neo4j

# Module-level APIs (preferred):
async with neo4j.session() as sess:
    # Use session
    pass

async with neo4j.run('MATCH (n) RETURN n', param=value) as result:
    records = await result.data()

# High-level operations:
await neo4j.initialize()  # Set up indexes
element_id = await neo4j.upsert(node_model, {'id': '123'})
await neo4j.aclose()  # Cleanup

# Cypherantic wrapper functions (type-safe Pydantic integration):
node_id = await neo4j.create_node(model_instance)  # Create node from model
edge_id = await neo4j.create_relationship(
    source_model, target_model, rel_type='DEPENDS_ON'
)
await neo4j.refresh_relationship(model, 'dependencies')  # Lazy-load relationships
edges = await neo4j.retrieve_relationship_edges(model, 'dependencies')
```

**Implementation details** (`src/imbi/neo4j/client.py`):
- `Neo4j.get_instance()`: Returns singleton driver instance
- Automatically reinitializes if event loop changes (important for FastAPI)
- Manages connection pool with keep-alive and max connection settings
- `initialize()` creates indexes defined in `neo4j/constants.py`

**Upsert pattern** (`neo4j/__init__.py:upsert()`):
- Uses Cypher `MERGE` with `ON CREATE SET` and `ON MATCH SET`
- Takes constraint dict for matching (e.g., `{'id': '123'}`)
- Automatically maps Pydantic model properties to node properties
- Returns Neo4j elementId of created/updated node

**Cypherantic integration** (`neo4j/__init__.py`):
- `create_node()`: Create Neo4j nodes from Pydantic models with automatic label/property mapping
- `create_relationship()`: Create typed relationships between nodes with optional properties
- `refresh_relationship()`: Lazy-load relationship properties from graph (on-demand fetching)
- `retrieve_relationship_edges()`: Fetch relationship edges as Pydantic models
- Full type safety with TypeVars preserving model types through operations

### Authentication & Authorization Pattern

The auth system provides OAuth2/OIDC and local password authentication with fine-grained permissions:

```python
from imbi.auth import permissions
import fastapi
import typing

@router.get('/resource')
async def get_resource(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('resource:read'))
    ]
) -> dict:
    """Endpoint requires 'resource:read' permission."""
    # auth.user contains authenticated user
    # auth.token_metadata contains JWT token info
    return {'user': auth.user.username}

# Check permissions programmatically
has_permission = await permissions.user_has_permission(
    user_id, 'resource:write'
)
```

**Authentication flow**:
1. User authenticates via OAuth provider or local password
2. Server issues JWT access token (15 min) and refresh token (7 days)
3. Client includes `Authorization: Bearer <token>` in requests
4. `require_permission()` dependency validates token and checks permissions
5. Endpoint receives `AuthContext` with user and token metadata

**Setup and seeding** (`auth/seed.py`, `entrypoint.py:setup`):
- Run `imbi setup` once to initialize a new instance
- Creates default roles (admin, developer, readonly) with permissions
- Interactively prompts for initial admin user creation
- Idempotent: checks if system is seeded before running
- No auto-seeding on startup (explicit setup required for security)

**OAuth providers** (`auth/oauth.py`):
- Google, GitHub, Keycloak support
- Configurable via environment variables (client ID, secret, discovery URLs)
- Automatic user creation on first OAuth login
- Links OAuth identity to user account

### FastAPI Application Structure

**Application factory** (`src/imbi/app.py`):
```python
from imbi.app import create_app

app = create_app()  # Returns configured FastAPI instance
```

**Lifespan management**: The application uses FastAPI's lifespan context manager to:
- Initialize Neo4j indexes on startup (`neo4j.initialize()`)
- Initialize ClickHouse connection and test connectivity (`clickhouse.initialize()`)
- Auto-seed authentication system with default roles and permissions (if not already seeded)
- Clean up Neo4j and ClickHouse connections on shutdown
- Ensures proper resource management across application lifecycle

**Endpoint registration** (`src/imbi/endpoints/`):
- Each endpoint module exports an `APIRouter`
- Routers collected in `endpoints/__init__.py:routers` list
- Automatically registered in `create_app()` via `app.include_router()`

**CLI interface** (`src/imbi/entrypoint.py`):
- Built with Typer for command-line operations
- `run-server`: Start uvicorn with development/production modes
- Configures logging, auto-reload, proxy headers, and custom Server header

### Data Modeling Conventions

1. **Pydantic models** (`src/imbi/models.py`):
   - Domain entities use `pydantic.BaseModel`
   - Keep models simple, focused on data structure
   - Model class names become Neo4j labels (lowercase)
   - Includes: Blueprint, User, Group, Role, Permission, Project, Organization, Team, etc.

2. **Settings** (`src/imbi/settings.py`):
   - Use `pydantic_settings.BaseSettings` for configuration
   - Prefix environment variables (e.g., `NEO4J_URL`, `CLICKHOUSE_URL`)
   - Support `.env` files with `BASE_SETTINGS` config dict
   - Separate settings classes for auth, Neo4j, ClickHouse

3. **Auth models** (`src/imbi/auth/models.py`):
   - JWT token payloads and metadata
   - OAuth provider configurations
   - Authentication request/response models

### Testing Patterns

Tests use `unittest.IsolatedAsyncioTestCase` for async support:

```python
class MyTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Reset singleton for test isolation
        client.Neo4j._instance = None
        # Set up mocks

    async def test_something(self) -> None:
        # Test async code
        pass
```

**Mocking async context managers**:
```python
mock_session = unittest.mock.AsyncMock()
mock_session.__aenter__.return_value = mock_session
mock_session.__aexit__.return_value = None
```

## Code Style

**Configured in `pyproject.toml`**:
- **Line length**: 79 characters
- **Quote style**: Single quotes
- **Python version**: 3.12+
- **Formatter**: Ruff (replaces Black)
- **Linter**: Ruff with comprehensive rules (see `tool.ruff.lint.select`)

**Key conventions**:
- Async/await for all I/O operations
- Context managers (`async with`) for resource management
- Module-level loggers: `LOGGER = logging.getLogger(__name__)`
- Type hints using modern syntax (`str | None`, not `Optional[str]`)
- `typing.LiteralString` for Cypher queries to ensure safety
- Security tests disabled in test files (`[tool.ruff.lint.per-file-ignores]`)

**Ignored rules**:
- `N818`: Exception class names don't need to end in "Error"
- `RSE`: Contradicts Python Style Guide
- `TRY003`: Message text in exception initializers is okay
- `TRY400`: logging.exception is not always preferable
- `UP040`: Allow non-PEP 695 type aliases
- `UP047`: Allow non-PEP 695 generic functions (TypeVars for cypherantic compatibility)

**Type checking**:
- **mypy**: Configured for strict type checking of `src/imbi` (run with `uv run mypy`)
- **pyright**: Configured to check `src/` and `tests/` with strict mode

## CI/CD

**GitHub Actions workflows** (`.github/workflows/`):

1. **`testing.yaml`**: Runs on every push to `main` and all pull requests
   - Tests across Python 3.12, 3.13, and 3.14
   - Uses `astral-sh/setup-uv@v7` for fast dependency installation
   - Runs pre-commit checks (linting, formatting)
   - Executes full test suite via `uv run pytest`
   - Uploads coverage reports to Codecov (90% minimum required)
   - Starts Docker services (Neo4j, ClickHouse, Jaeger) via bootstrap

2. **`docs.yaml`**: Builds and deploys documentation to GitHub Pages
   - Triggers on pushes to `main` affecting docs/ or mkdocs.yml
   - Uses Python 3.12 and pip for MkDocs dependencies
   - Builds with `mkdocs build --strict`
   - Deploys to GitHub Pages

3. **`deploy.yaml`**: Publishes releases to PyPI
   - Triggers on GitHub release creation
   - Uses Python 3.14
   - Builds wheel with `python -m build`
   - Validates with `twine check`
   - Publishes via trusted publisher (OIDC)

**Pre-commit hooks** (`.pre-commit-config.yaml`):
- Standard checks: trailing whitespace, EOF, YAML/TOML validation, merge conflicts
- Ruff: Linting with `--fix` and formatting

**Dependency management**:
- Dependencies locked in `uv.lock` for reproducibility
- Development dependencies in `[dependency-groups]` section
- Documentation dependencies in separate `docs` group

## Git Workflow

**Branching strategy**:
- Main development branch: `main`
- Feature branches: `feature/<feature-name>` (branch off from `main`)

**Creating pull requests**:
- All PRs should target the `main` branch
- Create feature branches from `main`
- Use descriptive branch names: `feature/blueprints`, `feature/api-endpoints`, etc.
- PR titles should be clear and concise
- Include comprehensive PR descriptions with:
  - Summary of changes
  - Testing instructions
  - Examples (if applicable)
  - List of commits

**Example workflow**:
```bash
# Create feature branch from main
git checkout main
git pull origin main
git checkout -b feature/new-feature

# Make changes, commit, and push
git add .
git commit -m "Add new feature"
git push -u origin feature/new-feature

# Create PR targeting main
gh pr create --base main --title "Add new feature" --body "..."
```

## Important Notes

**Current development status**: This is a v2 alpha rewrite. Core infrastructure and authentication complete with 315 tests (~30% coverage):

✅ **Implemented**:
- FastAPI application with lifespan management (Neo4j, ClickHouse init/cleanup, auto-seeding)
- Status endpoint with health check (`GET /status`)
- CLI with `run-server` command (development and production modes)
- Neo4j integration with singleton pattern, cypherantic wrappers, indexes, upsert operations
- ClickHouse integration with async client, schema management, insert/query operations
- Settings management via Pydantic with URL credential extraction
- Core domain models (Blueprint, User, Group, Role, Permission, Project, Organization, Team)
- Blueprint CRUD endpoints with permission-based authorization
- User/Group/Role management endpoints
- Authentication system:
  - OAuth2/OIDC support (Google, GitHub, Keycloak)
  - Local password authentication
  - JWT token generation and refresh
  - Auto-seeding of roles and permissions on startup
- Authorization system:
  - Permission-based access control
  - Resource-level permissions (read, write, delete)
  - Role-based authorization with group support
- Docker Compose development environment (Neo4j, ClickHouse, Jaeger)
- Pre-commit hooks with Ruff linting and formatting
- Bootstrap script for automated setup
- Test suite with 315 tests (coverage being expanded)

🚧 **In Progress**:
- Expanding test coverage to 90%+ (currently ~30%)
- Additional API endpoints (projects, organizations, teams, project types, environments)
- Webhook service for GitHub/PagerDuty integration
- Conversational AI features
- MCP server integration
- UI rewrite

**Database strategy**:
- **Neo4j**: Graph database for service relationships, dependencies, and user/permission model
- **ClickHouse**: Analytics and time-series data for operations logs and metrics

**Vector embeddings**: Configuration present for 1536-dimensional vectors with cosine similarity for AI-powered search (see `neo4j/constants.py`)

**Authentication/Authorization**: Full OAuth2/OIDC support with multiple providers, local password auth, JWT tokens, and fine-grained permission system integrated with all endpoints
