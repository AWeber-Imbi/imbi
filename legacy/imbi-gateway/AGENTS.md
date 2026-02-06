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

### Shared Library: imbi-common

The project depends heavily on the `imbi-common` library (from https://github.com/AWeber-Imbi/imbi-common), which provides:

- Server utilities via `imbi_common.server`
- Database connection helpers
- Common logging and telemetry patterns
- Shared Pydantic models

When adding server features, check `imbi-common` first to reuse existing patterns.

### Code Style

- **Line length**: 79 characters (strict)
- **Quotes**: Single quotes for strings
- **Type checking**: Strict mode enabled for both basedpyright and mypy
- **Coverage requirement**: 90% minimum
- Use type hints on all functions (enforced by strict type checking)

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
    - Tests across Python 3.12, 3.13, 3.14
- **`.github/workflows/docker.yml`**: Runs on release
    - Builds Python wheel
    - Publishes multi-arch Docker image to ghcr.io
    - Creates build attestations

## Project Dependencies

Key runtime dependencies (from `pyproject.toml`):

- `fastapi>=0.128.0`
- `imbi-common[server]` (git dependency, main branch)

The project uses `uv` for package management with `--frozen` flag in CI to ensure reproducible builds.
