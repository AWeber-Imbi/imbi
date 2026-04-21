# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Imbi is a DevOps Service Management Platform designed to manage large environments containing many services and applications. Version 2 (currently in alpha) is a complete rewrite using FastAPI, Apache AGE (PostgreSQL) for graph data, and ClickHouse for analytics.

**See [README.md](README.md)** for project overview and core concepts.

## Development Commands

This project uses [just](https://github.com/casey/just) as a command runner and [uv](https://docs.astral.sh/uv/) for Python package management:

```bash
just setup              # Install deps + pre-commit hooks (uv sync --all-groups --all-extras --frozen)
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

### Running Tests

```bash
just test tests/auth/test_permissions.py
just test tests/auth/test_permissions.py::PermissionTests::test_get_permissions
just test -v
```

### First-Time Setup

```bash
just setup
uv run imbi-api setup   # Seeds roles/permissions, creates initial admin user (interactive, idempotent)
```

### Environment Configuration

The `docker` recipe (run automatically by `just serve` and `just test`) starts Docker Compose services and generates a `.env` file with dynamically assigned ports. Docker services defined in `compose.yaml`:
- **Neo4j**: graph database (ports 7474, 7687) — *migration to PostgreSQL+AGE in progress*
- **ClickHouse**: analytics (ports 8123, 9000)
- **Jaeger**: OpenTelemetry tracing (ports 4317, 16686)
- **Mailpit**: SMTP testing (ports 1025, 8025)
- **LocalStack**: S3-compatible object storage (port 4566)

The server starts on `localhost:8000` by default (configurable via `IMBI_HOST` and `IMBI_PORT`).

## Code Architecture

### Source Layout

```
src/imbi_api/
├── app.py            # FastAPI application factory (create_app)
├── entrypoint.py     # CLI (Typer): `serve` and `setup` commands
├── lifespans.py      # Async lifespan hooks (ClickHouse, Graph, Email, Storage)
├── models.py         # Re-exports: imbi_common.models + domain.models
├── settings.py       # API-specific settings extending imbi_common.settings
├── relationships.py  # Hypermedia relationship link utilities
├── openapi.py        # Custom OpenAPI schema with blueprint-enhanced models
├── domain/
│   └── models.py     # API-specific models (APIKey, OAuth, ServiceAccount, etc.)
├── endpoints/        # FastAPI routers (registered via endpoints/__init__.py:routers)
├── auth/             # Auth system (permissions, seed, sessions, OAuth providers)
├── email/            # SMTP client + Jinja2 templates with DI
├── storage/          # S3 client via aioboto3 with DI
└── middleware/       # Rate limiting
```

**imbi_common** (external git dependency): Shared code across Imbi services — core domain models, graph pool (Apache AGE), ClickHouse client, Cypher query generation, settings, JWT/password hashing.

### Key Patterns

**Application factory** (`app.py`): `create_app()` composes lifespan hooks, CORS, rate limiting, and registers all routers from `endpoints/__init__.py`.

**Lifespan-based DI** (`lifespans.py`): Services are initialized/torn down via `imbi_common.lifespan.Lifespan`:
1. `clickhouse_hook` — init/close ClickHouse (module-level singleton)
2. `graph.graph_lifespan` — Graph pool (blueprint refresh registered via `graph.set_on_startup()` in `lifespans.py`)
3. `email_hook` — yields `(EmailClient, TemplateManager)` tuple
4. `storage_hook` — yields `StorageClient`

Each DI-managed service has a `dependencies.py` module with a `_get_*` function calling `context.get_state(hook)`, exposed as a type alias (e.g., `InjectStorageClient = Annotated[StorageClient, Depends(_get_storage_client)]`).

**Graph pool DI**: Injected via `graph.Pool` type alias (`Annotated[Graph, Depends(...)]`).

**Model re-exports** (`models.py`): Single import path combining `imbi_common.models` (shared domain: Blueprint, Organization, Project, etc.) and `imbi_api.domain.models` (API-specific: APIKey, OAuth, ServiceAccount, etc.).

### Graph Integration (Apache AGE)

```python
# In endpoint handlers — injected automatically:
@router.get('/items/')
async def list_items(db: graph.Pool) -> list[Item]:
    return await db.match(Item)

# CRUD: create, merge (upsert), match (query), delete
await db.create(node)
await db.merge(node, ['slug'])
results = await db.match(Model, {'slug': 'foo'})
await db.delete(node)
```

**Cypher template syntax** (AGE + `psycopg.sql.SQL.format()`):
- Parameters use `{param}` placeholders (NOT `$param`)
- Property maps must double-escape braces: `{{key: {value}}}`
- AGE has no `ON CREATE SET` / `ON MATCH SET` — use plain `SET`
- Timestamps are stored as ISO strings (no `datetime()` function)

### Authentication & Authorization

```python
@router.get('/resource')
async def get_resource(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('resource:read'))
    ]
) -> dict:
    # auth.user, auth.token_metadata
    return {'user': auth.user.username}
```

Flow: OAuth/password -> JWT access token (15 min) + refresh token (7 days) -> `Authorization: Bearer <token>` -> `require_permission()` validates and checks permissions.

### Testing Patterns

Tests use `unittest.IsolatedAsyncioTestCase`. Override DI dependencies via `app.dependency_overrides`:

```python
from imbi_api.storage.dependencies import _get_storage_client
mock_storage = unittest.mock.AsyncMock(spec=StorageClient)
app.dependency_overrides[_get_storage_client] = lambda: mock_storage
```

Coverage target: 90% (`pyproject.toml` `tool.coverage.report.fail_under`). Current: ~30%.

## Code Style

- **Line length**: 79 characters
- **Quote style**: Single quotes
- **Python version**: 3.14+
- **Formatter/Linter**: Ruff (configured in `pyproject.toml`)
- **Type checking**: basedpyright (strict, `src/` + `tests/`) and mypy (strict, `mypy.ini`, `src/imbi_api` only)
- **Pre-commit hooks**: trailing whitespace, EOF fixer, YAML/TOML checks, debug statements, Ruff lint+format, tombi-format (TOML), mypy
- Always run `just format <filename>` on modified files before returning control to the user, running tests, or committing

**Conventions**:
- Async/await for all I/O operations
- Module-level loggers: `LOGGER = logging.getLogger(__name__)`
- Modern type hints (`str | None`, not `Optional[str]`)
- `typing.LiteralString` for Cypher queries
- **Prefer `typing.Literal` over `enum.StrEnum`** for constrained string fields — simple strings are the only type natively supported across AGE, ClickHouse, JSON, and msgpack

**Ignored ruff rules**: `N818`, `RSE`, `S105`/`S106`, `TRY003`, `TRY400`, `UP040`, `UP047`. Security rules (`S`) disabled in `tests/`.

## CI/CD

**GitHub Actions** (`.github/workflows/`):
- `testing.yaml`: Lint (`just lint`) + tests (`just test`) on Python 3.14 on every push/PR to `main`. Coverage uploaded to Codecov.
- `docs.yaml`: MkDocs build/deploy to GitHub Pages on doc changes.
- `deploy.yaml`: On release — `uv build`, multi-platform Docker image to `ghcr.io`, provenance attestation.

## Git Workflow

- Main branch: `main`
- Feature branches: `feature/<feature-name>`
- All PRs target `main`
