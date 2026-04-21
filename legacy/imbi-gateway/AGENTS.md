# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) and other AI agents when working with code in this repository.

## Project Overview

Imbi Gateway is an inbound webhook gateway service that receives external events, records them, and routes them through a workflow engine for processing. It acts as the central integration point between external systems (GitHub, PagerDuty, etc.) and internal services like imbi-automations.

Built with:

- FastAPI for the web framework
- `imbi-common` library (shared across Imbi services) for server utilities and common functionality
- Typer for CLI commands
- Pydantic for data validation and settings management

## Development Commands

### Environment Setup

```bash
just setup              # Set up development environment (install deps + pre-commit hooks)
```

### Running the Service

```bash
just serve              # Run the service in the foreground
```

### Testing

```bash
just test               # Run all tests with coverage
```

### Linting and Type Checking

```bash
just lint               # Run all linters (pre-commit, basedpyright, mypy)
```

### Formatting

```bash
just format             # Format all files using ruff and tombi
just format <file>      # Format a specific file (useful for editor hooks)
```

### Cleanup

```bash
just clean              # Remove runtime artifacts (.coverage, build/, etc.)
just real-clean         # Remove everything including .venv and caches (requires confirmation)
```

## Architecture

### Application Structure

- **`src/imbi_gateway/app.py`**: Main application entry point
    - `create_app()`: FastAPI application factory
    - `cli`: Typer CLI with commands (currently just `serve`)
    - Uses `imbi_common.server.bind_entrypoint()` to create the `serve` command

- **`tests/helpers.py`**: Base test case using `unittest.IsolatedAsyncioTestCase`
    - All test classes should inherit from `helpers.TestCase` for async test support

### Lifespan Management Pattern

**Problem:** FastAPI's `lifespan` parameter accepts only one callable, but
applications need multiple independent resources (database pools, Redis
connections) with separate setup/teardown lifecycles.

**Solution:** The `Lifespan` class in `src/imbi_gateway/lifespan.py`
composes multiple async context managers into a single lifespan while
preserving type information through dependency injection. This enables
type-safe access to lifespan-managed resources in route handlers.

**Standard Usage Pattern:**

1. **Define a lifespan hook** as an async context manager that yields the
   resource:

   ```python
   @contextlib.asynccontextmanager
   async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
       async with psycopg_pool.AsyncConnectionPool(...) as pool:
           await pool.open(wait=True)
           yield pool
   ```

2. **Create a dependency injection function** that retrieves the resource
   using `get_state()`:

   ```python
   async def _get_postgres_cursor(
       context: lifespan.InjectLifespan
   ) -> abc.AsyncIterator[CursorType]:
       pool = context.get_state(postgres_lifespan)
       async with pool.connection() as conn:
           async with conn.cursor() as cursor:
               yield cursor
   ```

3. **Define a type alias** for dependency injection:

   ```python
   PostgresCursor = typing.Annotated[
       CursorType, fastapi.Depends(_get_postgres_cursor)
   ]
   ```

4. **Combine hooks** when creating the FastAPI application:

   ```python
   app = fastapi.FastAPI(
       lifespan=lifespan.Lifespan(postgres_lifespan, redis_lifespan)
   )
   ```

5. **Use the type alias** in route handler parameters:

   ```python
   @app.get('/data')
   async def handler(*, cursor: PostgresCursor) -> None:
       await cursor.execute('SELECT ...')
   ```

**Type Safety:** The `TypedLifespanHook[T]` type alias and generic
`get_state()` method preserve type information through the dependency
chain, enabling strict type checking and IDE autocomplete for resources.

**Key Files:**

- `src/imbi_gateway/lifespan.py` - Implementation with module docstring
- `tests/test_lifespan.py` - 10 test cases with examples and edge cases
- `docs/lifespan-pattern.md` - Comprehensive tutorial and API reference

### Shared Library: imbi-common

The project depends heavily on the `imbi-common` library (from https://github.com/AWeber-Imbi/imbi-common), which provides:

- Server utilities via `imbi_common.server`
- Database connection helpers
- Common logging and telemetry patterns
- Shared Pydantic models

When adding server features, check `imbi-common` first to reuse existing patterns.

### Code Style and Formatting

**CRITICAL:** Do not attempt to manually apply formatting rules. The automated formatting tools (ruff, tombi) are the sole authority on code formatting. Their rules are complex and nuanced - what may appear as a formatting error to a human or AI agent may be intentionally allowed by the tools.

**Formatting workflow:**
1. Write code without worrying about formatting details
2. Run `just format` to apply automated formatting
3. If linting fails, run `just lint` to see errors
4. The tools will auto-fix what they can; manually fix only what they flag as errors

**Formatting tools and configuration:**
- **Ruff**: Python code formatting and linting (configured in `pyproject.toml`)
  - Enforces line length (79 characters with nuanced exceptions)
  - Enforces single quotes for most strings, triple double quotes for docstrings
  - Auto-fixes many linting issues with `ruff-check --fix`
- **Tombi**: TOML file formatting (configured in `.pre-commit-config.yaml`)
- **Pre-commit hooks**: Automatically run formatters on commit (installed via `just setup`)

**Other style requirements:**
- **Type checking**: Strict mode enabled for both basedpyright and mypy
- **Coverage requirement**: 90% minimum
- Use type hints on all functions (enforced by strict type checking)

**For AI agents:** Never suggest formatting changes or apply manual formatting corrections. Instead, direct users to run `just format` to apply automated formatting, or `just lint` to check for errors.

### Pre-commit Hooks

The repository uses pre-commit with:

- Standard file checks (JSON, YAML, TOML validation, trailing whitespace, etc.)
- Ruff for linting and formatting
- Tombi for TOML formatting

Pre-commit runs automatically on commit after running `just setup`.

## Docker

Build and run with Docker:

```bash
# Build requires dist/*.whl files first
uv build
docker build -t imbi-gateway .
docker run -p 8000:8000 imbi-gateway
```

The Dockerfile uses a multi-stage build:

1. Builder stage: Installs uv, dependencies, and the wheel file
2. Service stage: Minimal runtime with Python 3.14-slim

## CI/CD

GitHub Actions workflows:

- **`.github/workflows/test.yml`**: Runs on push/PR
    - Static analysis (pre-commit, basedpyright, mypy)
    - Tests on Python 3.14
- **`.github/workflows/docker.yml`**: Runs on release
    - Builds Python wheel
    - Publishes multi-arch Docker image to ghcr.io
    - Creates build attestations

## Project Dependencies

Key runtime dependencies (from `pyproject.toml`):

- `fastapi>=0.128.0`
- `imbi-common[server]` (git dependency, main branch)

The project uses `uv` for package management with `--frozen` flag in
CI to ensure reproducible builds.

### Managing Dependencies

**CRITICAL:** When working with project dependencies, follow these rules:

1. **Do not add unnecessary dependencies**
   - Only add packages that are truly required for the implementation
   - Check if functionality is available in Python's standard library
     before adding a third-party package
   - Example: `pathlib` is part of the standard library (Python ≥3.4)
     and should not be added as a dependency

2. **Ask when uncertain**
   - If you cannot determine whether a package is necessary, ask the
     human in the loop before adding it
   - Consider whether the functionality could be implemented without an
     additional dependency

3. **NEVER edit pyproject.toml directly**
   - Always use `uv` commands to manage dependencies
   - To add a dependency: `uv add package-name`
   - To remove a dependency: `uv remove package-name`
   - To add a dev dependency: `uv add --dev package-name`
   - Direct edits to `pyproject.toml` bypass `uv`'s dependency
     resolution and lock file management
