# Agent Instructions for imbi-mcp

## Project Overview

imbi-mcp is an MCP (Model Context Protocol) server that auto-generates tools
and resources from the imbi-api OpenAPI specification. It acts as a bridge
between AI agents and the Imbi DevOps service management platform.

## Architecture

```
AI Agent ──MCP──► imbi-mcp ──HTTP──► imbi-api ──► Neo4j / ClickHouse
```

- `src/imbi_mcp/server.py` -- Core server logic. Fetches the OpenAPI spec
  from imbi-api at startup and generates MCP tools/resources via FastMCP.
  Route maps control which endpoints are exposed and how they are classified.
- `src/imbi_mcp/app.py` -- Typer CLI entry point. The `serve` command
  creates the server and starts it on the configured transport.
- `src/imbi_mcp/__init__.py` -- Package version from installed metadata.

## Key Design Decisions

- The server requires a running imbi-api instance at startup to fetch the
  OpenAPI spec. If the API is unreachable, startup fails with a clear error.
- Auth is forwarded transparently: the MCP caller's `Authorization` header
  is injected into every request to imbi-api via an httpx event hook.
- Route maps are evaluated in order (first match wins). Exclusions come
  before semantic mappings.

## Code Standards

- **Line length**: 79 characters
- **Quotes**: Single quotes for strings, double quotes for docstrings
- **Type checking**: basedpyright strict mode + mypy strict mode
- **Testing**: unittest, 90% minimum coverage
- **Imports**: Prefer module imports (`from unittest import mock`)
  over object imports (`from unittest.mock import patch`)
- **Logging**: Use `%s` formatting, not f-strings
- **Async**: All I/O in production code must be async

## Development Commands

```bash
just setup       # Install dependencies and pre-commit hooks
just test        # Run pytest with coverage
just lint        # Run pre-commit, basedpyright, mypy
just format      # Auto-format with ruff and tombi
```

## Testing

Tests use `unittest.TestCase` and `unittest.IsolatedAsyncioTestCase`.
All external I/O (httpx calls, FastMCP context) is mocked.

```bash
uv run pytest                    # Run all tests
uv run pytest tests/test_server.py  # Run specific test file
```

## CI/CD

GitHub Actions runs on Python 3.12, 3.13, and 3.14:
- **Static Analysis**: pre-commit hooks + basedpyright
- **Automated Tests**: pytest with coverage reporting

## Dependencies

- **fastmcp** -- MCP server framework with OpenAPI auto-generation
- **httpx** -- Async HTTP client for API communication
- **imbi-common** -- Shared models and utilities (installed from git)
- **typer** -- CLI framework (via fastmcp dependency)

Manage dependencies with `uv`. After changing `pyproject.toml`, run
`uv lock` to update the lock file.
