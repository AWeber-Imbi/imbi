# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Imbi is a DevOps Service Management Platform designed to manage large environments containing many services and applications. Version 2 (currently in alpha) is a complete rewrite using FastAPI, Neo4j for graph data, and ClickHouse for analytics.

## Development Setup

### Initial Setup
```bash
./bootstrap
```
This script:
- Creates/activates a Python virtual environment
- Installs the package with dev dependencies
- Installs pre-commit hooks
- Starts Docker Compose services (Neo4j, ClickHouse)
- Waits for services to be healthy (120s timeout)

### Environment Configuration
Services run without authentication in development (configured in `compose.yaml`):
- Neo4j: ports 7474 (HTTP), 7687 (Bolt) - `NEO4J_AUTH=none`
- ClickHouse: ports 8123 (HTTP), 9000 (Native) - default/password

Override settings via environment variables or `.env` file:
```bash
NEO4J_URL=neo4j://localhost:7687
NEO4J_USER=username
NEO4J_PASSWORD=password
```

## Common Development Commands

### Code Quality
```bash
# Run all pre-commit checks (includes ruff linting + formatting)
pre-commit run --all-files

# Run ruff directly
ruff check .                    # Lint
ruff check --fix .             # Lint with auto-fix
ruff format .                   # Format code
```

### Testing
```bash
# Run all tests with coverage
coverage run && coverage report

# Run specific test file
python -m pytest tests/neo4j/test_client.py

# Run specific test class or method
python -m pytest tests/neo4j/test_client.py::Neo4jClientTestCase
python -m pytest tests/neo4j/test_client.py::Neo4jClientTestCase::test_singleton

# Run with verbose output
python -m pytest -v tests/
```

**Coverage requirement**: 90% minimum (enforced in `pyproject.toml`)

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
  - `models.py`: Core domain models (Namespace, ProjectType, Project)
  - `settings.py`: Configuration via Pydantic Settings
  - `neo4j/`: Neo4j graph database integration layer
- **`tests/`**: Test suite organized by module

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

### Data Modeling Conventions

1. **Pydantic models** (`src/imbi/models.py`):
   - Domain entities use `pydantic.BaseModel`
   - Keep models simple, focused on data structure
   - Model class names become Neo4j labels (lowercase)

2. **Settings** (`src/imbi/settings.py`):
   - Use `pydantic_settings.BaseSettings` for configuration
   - Prefix environment variables (e.g., `NEO4J_URL`)
   - Support `.env` files with `BASE_SETTINGS` config dict

3. **Neo4j models** (`src/imbi/neo4j/models.py`):
   - `Node`: Represents graph nodes with labels and properties
   - `coerce_neo4j_datetime()`: Convert Neo4j DateTime to Python datetime

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
- `E501`: Line too long (many long Pydantic model descriptions)
- `N818`: Exception class names don't need to end in "Error"
- `UP040`: Allow non-PEP 695 type aliases

## CI/CD

**GitHub Actions workflows** (`.github/workflows/`):
- `testing.yaml`: Runs on Python 3.12, includes pre-commit checks, pytest with 90% coverage, Codecov upload
- `docs.yaml`: Builds and deploys MkDocs documentation to GitHub Pages

**Pre-commit hooks** (`.pre-commit-config.yaml`):
- Standard checks: trailing whitespace, EOF, YAML/TOML validation, merge conflicts
- Ruff: Linting with `--fix` and formatting

## Important Notes

**Current development status**: This is a v2 alpha rewrite. Core infrastructure is in place:
- ✅ Neo4j integration with singleton pattern, indexes, upsert operations
- ✅ Settings management via Pydantic
- ✅ Docker Compose development environment
- 🚧 ClickHouse integration (dependency present, service running, but not yet integrated in code)
- 🚧 FastAPI routes/endpoints (dependency present but no routes yet)

**Database strategy**:
- **Neo4j**: Graph database for service relationships and dependencies
- **ClickHouse**: Analytics and time-series data (planned)

**Vector embeddings**: Configuration present for 1536-dimensional vectors with cosine similarity (see `neo4j/constants.py`)
