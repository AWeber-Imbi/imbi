# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Imbi is a DevOps Service Management Platform designed to manage large environments containing many services and applications. Version 2 (currently in alpha) is a complete rewrite using FastAPI, Apache AGE (PostgreSQL) for graph data, and ClickHouse for analytics.

**See [README.md](README.md)** for project overview, core concepts, and full v2 roadmap including conversational AI, webhook workflows, MCP server integration, and ecosystem of services.

## Development Setup

### Package Manager

This project uses [uv](https://docs.astral.sh/uv/) for fast, reliable Python package management. Dependencies are locked in `uv.lock` for reproducible builds.

### Initial Setup
```bash
# Step 1: Set up development environment
just setup

# Step 2: Initialize Imbi (first time only)
uv run imbi-api setup
```

`just setup`:
- Syncs dependencies using `uv sync --all-extras --all-groups --frozen`
- Installs pre-commit hooks via `uv run pre-commit install --install-hooks --overwrite`

The `imbi-api setup` command (run once per instance):
- Seeds permissions and default roles (admin, developer, readonly)
- Interactively creates the initial admin user
- Idempotent: safe to run multiple times (prompts before creating duplicates)

### Environment Configuration

**Docker services** (configured in `compose.yaml`):
- **PostgreSQL+AGE**: port 5432
- **ClickHouse**: ports 8123 (HTTP), 9000 (Native) - default/password
- **Jaeger**: ports 4317 (OTLP), 16686 (UI) - for OpenTelemetry tracing

The `docker` recipe (run automatically by `just serve` and `just test`) starts Docker Compose services, creates the ClickHouse database, and generates a `.env` file with dynamically assigned ports and OpenTelemetry configuration. You can override settings via environment variables:

```bash
POSTGRES_URL=postgresql://postgres:secret@localhost:5432/imbi
```

**PostgreSQL connection**: Settings use `POSTGRES_URL` environment variable with standard PostgreSQL DSN format. Pool size configured via `POSTGRES_MIN_POOL_SIZE` and `POSTGRES_MAX_POOL_SIZE`.


## Development Commands

This project uses [just](https://github.com/casey/just) as a command runner:

```bash
just setup              # Set up development environment (install deps + pre-commit hooks)
just serve              # Setup + docker + run the API server
just serve --dev        # Run with auto-reload
just test               # Setup + docker + run all tests with coverage
just test <test>        # Run a single test using pytest syntax
just lint               # Setup + run pre-commit, basedpyright, mypy
just format             # Setup + reformat all files
just format <file>      # Reformat a specific file
just clean              # Remove runtime artifacts + tear down docker
just real-clean         # Remove everything including .venv and caches (with confirmation)
```

The server starts on `localhost:8000` by default (configurable via `IMBI_HOST` and `IMBI_PORT`).

### Running Tests Directly
```bash
# Run specific test file
just test tests/auth/test_permissions.py

# Run specific test class or method
just test tests/auth/test_permissions.py::PermissionTests
just test tests/auth/test_permissions.py::PermissionTests::test_get_permissions

# Run with verbose output
just test -v
```

**Coverage configuration** (`pyproject.toml`):
- Minimum coverage target: 90% (configured via `tool.coverage.report.fail_under`)
- Current coverage: ~30% (expanded functionality requires additional test coverage)
- Automatic coverage collection via `pytest --cov` (configured in `tool.pytest.ini_options.addopts`)
- XML output: `build/coverage.xml` (for Codecov)
- HTML report: `build/coverage/` (for local review)

## Code Architecture

### High-Level Structure
- **`src/imbi_api/`**: Main application code
  - `app.py`: FastAPI application factory with lifespan management
  - `entrypoint.py`: CLI commands (Typer-based) including `setup` and `serve`
  - `endpoints/`: API endpoint routers
    - `status.py`: Health check endpoint
    - `auth.py`: Authentication (OAuth2/OIDC, local password) and token management
    - `users.py`: User CRUD operations
    - `groups.py`: Group CRUD operations
    - `roles.py`: Role CRUD operations
    - `blueprints.py`: Blueprint CRUD operations
  - `auth/`: Authentication and authorization system
    - `permissions.py`: Permission checking and resource-based authorization
    - `seed.py`: Auth system seeding (roles and permissions)
    - `sessions.py`: Session management
    - `oauth.py`: OAuth2/OIDC provider integration (Google, GitHub, Keycloak)
  - `email/`: Email notification system
    - `client.py`: SMTP client with retry logic
    - `templates.py`: Jinja2 email template rendering
    - `dependencies.py`: DI injection (`InjectEmailClient`, `InjectTemplateManager`)
  - `storage/`: S3-compatible object storage
    - `client.py`: Async S3 client via aioboto3
    - `dependencies.py`: DI injection (`InjectStorageClient`)
  - `middleware/`: FastAPI middleware (rate limiting)
  - `openapi.py`: Custom OpenAPI schema generation
- **`imbi_common` package** (external dependency): Shared code used across Imbi services
  - `models.py`: Core domain models (Blueprint, User, Group, Role, Permission, Project, etc.)
  - `settings.py`: Configuration via Pydantic Settings with URL credential extraction
  - `blueprints.py`: Blueprint filtering and schema validation logic
  - `graph.py`: Apache AGE (PostgreSQL) async connection pool, Cypher execution, DI via `graph.Pool`
  - `cypher.py`: Cypher query generation from Pydantic models
  - `clickhouse/`: ClickHouse analytics database integration
    - `client.py`: Async ClickHouse client with connection pooling
    - `__init__.py`: High-level API for queries and inserts
  - `auth/core.py`: JWT token generation and password hashing
  - `logging.py`: Logging configuration
- **`tests/`**: Test suite with ~30% coverage, being expanded

### ClickHouse Integration Pattern

The ClickHouse module provides async operations for analytics and time-series data:

```python
from imbi_common import clickhouse

# Initialize connection (called during app startup)
await clickhouse.initialize()

# Insert Pydantic models
from imbi_common.models import SomeModel
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

**Implementation details** (`imbi_common/clickhouse/client.py`):
- Singleton pattern with async connection management
- Automatic Pydantic model serialization for inserts
- Support for nested/complex types via flattening
- Connection pooling and health checks

### Graph Integration Pattern (Apache AGE)

The graph module uses **dependency injection via FastAPI**:

```python
from imbi_common import graph

# In endpoint handlers — injected automatically:
@router.get('/items/')
async def list_items(db: graph.Pool) -> list[Item]:
    return await db.match(Item)

# High-level CRUD:
await db.create(node)           # Create node + edges
await db.merge(node, ['slug'])  # Upsert by match keys
results = await db.match(Model, {'slug': 'foo'})
await db.delete(node)           # DETACH DELETE

# Raw Cypher (AGE-compatible):
records = await db.execute(
    'MATCH (n:User {{email: {email}}}) RETURN n',
    {'email': 'user@example.com'},
)
# Multi-column returns:
records = await db.execute(
    'MATCH (u:User)-[r]->(o:Organization) RETURN u, o',
    columns=['u', 'o'],
)
# Parse raw agtype values:
props = graph.parse_agtype(records[0]['u'])
```

**Cypher template syntax** (AGE + `psycopg.sql.SQL.format()`):
- Parameters use `{param}` placeholders (NOT `$param`)
- Property maps must double-escape braces: `{{key: {value}}}`
- AGE has no `ON CREATE SET` / `ON MATCH SET` — use plain `SET`
- Timestamps are stored as ISO strings (no `datetime()` function)

**Implementation** (`imbi_common/graph.py`):
- `Graph` class wraps `psycopg_pool.AsyncConnectionPool`
- `graph_lifespan()` manages pool open/close in FastAPI lifespan
- `Pool` type alias for DI: `typing.Annotated[Graph, Depends(...)]`
- Settings from `settings.Postgres` (env prefix `POSTGRES_`)

### Authentication & Authorization Pattern

The auth system provides OAuth2/OIDC and local password authentication with fine-grained permissions:

```python
from imbi_api.auth import permissions
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

**Setup and seeding** (`src/imbi_api/auth/seed.py`, `src/imbi_api/entrypoint.py:setup`):
- Run `imbi-api setup` once to initialize a new instance
- Creates default roles (admin, developer, readonly) with permissions
- Interactively prompts for initial admin user creation
- Idempotent: checks if system is seeded before running
- No auto-seeding on startup (explicit setup required for security)

**OAuth providers** (`src/imbi_api/auth/oauth.py`):
- Google, GitHub, Keycloak support
- Configurable via environment variables (client ID, secret, discovery URLs)
- Automatic user creation on first OAuth login
- Links OAuth identity to user account

### FastAPI Application Structure

**Application factory** (`src/imbi_api/app.py`):
```python
from imbi_api.app import create_app

app = create_app()  # Returns configured FastAPI instance
```

**Lifespan management**: The application uses `imbi_common.lifespan.Lifespan` to compose multiple async context manager hooks (`src/imbi_api/lifespans.py`):

1. `clickhouse_hook` — init/close ClickHouse connection
2. `graph.graph_lifespan` — open/close Graph connection pool and refresh blueprint models for OpenAPI schema (combined via monkey-patch in `lifespans.py`)
3. `email_hook` — creates `EmailClient` + `TemplateManager`, yields `tuple[EmailClient, TemplateManager]`
4. `storage_hook` — creates `StorageClient`, yields it

Hooks that yield resources (email, storage, graph) use the `Lifespan.get_state()` DI pattern — see "Dependency Injection Pattern" below. Graph is DI-managed via `graph.Pool`; ClickHouse still uses a module-level singleton.

**Endpoint registration** (`src/imbi_api/endpoints/`):
- Each endpoint module exports an `APIRouter`
- Routers collected in `endpoints/__init__.py:routers` list
- Automatically registered in `create_app()` via `app.include_router()`

**CLI interface** (`src/imbi_api/entrypoint.py`):
- Built with Typer for command-line operations
- Entry point: `imbi-api` command (defined in `pyproject.toml`)
- `serve`: Start uvicorn with development/production modes
- `setup`: Initialize Imbi with authentication system and admin user
- Configures logging, auto-reload, proxy headers, and custom Server header

### Dependency Injection Pattern

Email and storage use `imbi_common.lifespan.Lifespan` for type-safe DI. The pattern has three parts:

1. **Lifespan hook** (`lifespans.py`) — async context manager that creates, yields, and cleans up a resource.
2. **Dependency function** (`*/dependencies.py`) — calls `context.get_state(hook)` to retrieve the yielded resource.
3. **Type alias** — `Annotated[T, Depends(fn)]` used as a parameter type in endpoint handlers.

```python
from imbi_api.storage import InjectStorageClient

@router.post('/uploads/')
async def create_upload(
    file: fastapi.UploadFile,
    storage_client: InjectStorageClient,
) -> dict:
    await storage_client.upload(key, data, content_type)
```

**Testing with DI**: Override the dependency function in `app.dependency_overrides` instead of patching module-level imports:

```python
from imbi_api.storage.dependencies import _get_storage_client

mock_storage = unittest.mock.AsyncMock(spec=StorageClient)
app.dependency_overrides[_get_storage_client] = lambda: mock_storage
```

**Not yet DI'd**: ClickHouse still uses a module-level singleton in `imbi_common`.

### Data Modeling Conventions

1. **Pydantic models** (`imbi_common/models.py`):
   - Domain entities use `pydantic.BaseModel`
   - Keep models simple, focused on data structure
   - Model class names become AGE vertex labels
   - Includes: Blueprint, User, Group, Role, Permission, Project, Organization, Team, etc.
   - **Prefer `typing.Literal` over `enum.StrEnum`** for constrained string fields (e.g., `typing.Literal['active', 'inactive']`). Simple strings are the only type natively supported across AGE/PostgreSQL, ClickHouse, JSON, and msgpack — avoid enums, pattern matching on enum values, or other alternatives.

2. **Settings** (`imbi_common/settings.py`):
   - Use `pydantic_settings.BaseSettings` for configuration
   - Prefix environment variables (e.g., `POSTGRES_URL`, `CLICKHOUSE_URL`)
   - Support `.env` files
   - Separate settings classes for auth, Postgres, ClickHouse, server, email

3. **Auth models** (`imbi_common/auth/models.py`):
   - JWT token payloads and metadata
   - OAuth provider configurations
   - Authentication request/response models

### Testing Patterns

Tests use `unittest.IsolatedAsyncioTestCase` for async support:

```python
class MyTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mock_db = unittest.mock.AsyncMock(spec=graph.Graph)
        # Set up mocks

    async def test_something(self) -> None:
        # Pass mock_db to functions: await some_func(self.mock_db, ...)
        pass
```

**DI-managed services** (graph, email, storage): Use `dependency_overrides` on the FastAPI app:

```python
from imbi_api.storage.dependencies import _get_storage_client

mock_storage = mock.AsyncMock(spec=StorageClient)
app.dependency_overrides[_get_storage_client] = lambda: mock_storage
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
- `UP047`: Allow non-PEP 695 generic functions

**Formatting**:
- Always run `just format <filename>` on modified files before returning control to the user, running tests, or committing

**Type checking**:
- **mypy**: Configured for strict type checking of `src/imbi_api`
- **basedpyright**: Configured to check `src/` and `tests/` with strict mode
- Run both via `just lint`

## CI/CD

**GitHub Actions workflows** (`.github/workflows/`):

1. **`testing.yaml`**: Runs on every push to `main` and all pull requests
   - Tests across Python 3.12, 3.13, and 3.14
   - Uses `astral-sh/setup-uv@v7` for fast dependency installation
   - Runs pre-commit checks (linting, formatting)
   - Executes full test suite via `uv run pytest`
   - Uploads coverage reports to Codecov (90% minimum required)
   - Starts Docker services (PostgreSQL+AGE, ClickHouse, Jaeger) via bootstrap

2. **`docs.yaml`**: Builds and deploys documentation to GitHub Pages
   - Triggers on pushes to `main` affecting docs/ or mkdocs.yml
   - Uses Python 3.12 and pip for MkDocs dependencies
   - Builds with `mkdocs build --strict`
   - Deploys to GitHub Pages

3. **`deploy.yaml`**: Builds and publishes Docker image
   - Triggers on GitHub release publication
   - Builds Python package with `uv build` and attaches distributions to the GitHub release
   - Builds multi-platform Docker image (linux/amd64, linux/arm64)
   - Publishes to `ghcr.io` with semver tags
   - Attests build provenance via `actions/attest-build-provenance`

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

**Current development status**: This is a v2 alpha rewrite. Core infrastructure and authentication complete (~30% test coverage):

✅ **Implemented**:
- FastAPI application with lifespan management (Graph, Email, Storage DI-managed via lifespan hooks; ClickHouse remains module-level singleton)
- Status endpoint with health check (`GET /status`)
- CLI with `serve` and `setup` commands (development and production modes)
- Apache AGE integration with DI-managed Graph pool, Cypher execution, model CRUD
- ClickHouse integration with async client, schema management, insert/query operations
- Settings management via Pydantic with URL credential extraction
- Core domain models (Blueprint, User, Group, Role, Permission, Project, Organization, Team)
- Blueprint CRUD endpoints with permission-based authorization
- User/Group/Role management endpoints
- Authentication system:
  - OAuth2/OIDC support (Google, GitHub, Keycloak)
  - Local password authentication
  - JWT token generation and refresh
  - MFA/TOTP support
  - Seeding of roles and permissions via `imbi-api setup` command
- Authorization system:
  - Permission-based access control
  - Resource-level permissions (read, write, delete)
  - Role-based authorization with group support
- Email notification system (DI-managed via lifespan hooks)
- S3-compatible object storage with upload validation and thumbnails (DI-managed)
- Docker Compose development environment (PostgreSQL+AGE, ClickHouse, Jaeger, Mailpit)
- Pre-commit hooks with Ruff linting and formatting
- Justfile for consistent developer workflow (matching imbi-common and imbi-gateway)
- Test suite (coverage being expanded to 90%+)

🚧 **In Progress**:
- Expanding test coverage to 90%+ (currently ~30%)
- Additional API endpoints (projects, organizations, teams, project types, environments)
- Webhook service for GitHub/PagerDuty integration
- Conversational AI features
- MCP server integration
- UI rewrite

**Database strategy**:
- **Apache AGE (PostgreSQL)**: Graph database for service relationships, dependencies, and user/permission model
- **ClickHouse**: Analytics and time-series data for operations logs and metrics

**Vector embeddings**: Configuration present for AI-powered search using pgvector (PostgreSQL extension)

**Authentication/Authorization**: Full OAuth2/OIDC support with multiple providers, local password auth, JWT tokens, and fine-grained permission system integrated with all endpoints
