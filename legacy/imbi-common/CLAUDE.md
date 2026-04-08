# AGENTS.md

This file provides guidance to Agents (eg, Claude Code) when working with code in this repository.

## Commands

This project uses `just` as a task runner and `uv` for Python package management.

```bash
just setup        # Install dependencies and pre-commit hooks
just docker       # Bootstrap the docker environment and setup database schema
just test         # Run full test suite with coverage (requires Docker)
just test <file>  # Run specific test file(s) without coverage
just lint         # Run all linters via pre-commit
just format       # Reformat code (ruff + tombi)
just docs         # Generate documentation into `site`
just clean        # Tear down Docker, remove .env and build artifacts
just real-clean   # Remove .venv and all caches (prompts for confirmation)
```

The `just test` target automatically starts Docker services (PostgreSQL with AGE + ClickHouse), creates a `.env` file with connection URLs, and runs coverage. When running specific files, the `.env` must already exist or env vars must be set.

Running individual tests (e.g., during iteration):

```bash
just test tests/path/to/test_file.py
just test tests/path/to/test_file.py::TestClass::test_method
```

## Architecture

`imbi-common` is a shared library consumed by `imbi-api`, `imbi-gateway`, and `imbi-mcp`. Source lives in `src/imbi_common/`, tests in `tests/`.

### Module map

| Module               | Purpose                                                                                                                                                                                                     |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `graph.py`           | Apache AGE (PostgreSQL extension) async client — `Graph` class with psycopg v3 pool and high-level methods (`create`, `delete`, `match`, `merge`, `execute`)                                               |
| `cypher.py`          | Cypher query generation from Pydantic models — `create`, `delete`, `match`, `merge` return `Statement` named tuples with templates and parameters                                                          |
| `clickhouse/`        | ClickHouse async client singleton with `query()` / `insert()`, schema setup via `schemata.toml`, and privacy utilities                                                                                     |
| `models.py`          | Pydantic domain models (`Project`, `Team`, `Environment`, `Organization`, `ProjectType`, `Blueprint`) with `Edge` dataclass metadata for graph relationships                                                |
| `blueprints.py`      | Runtime schema extension system — loads `Blueprint` nodes from the graph and uses `pydantic.create_model` to dynamically add fields to existing models                                                      |
| `settings.py`        | Pydantic Settings classes (`Postgres`, `Clickhouse`, `Auth`) plus `Configuration` for TOML file loading. Settings pick up env vars with prefixes `POSTGRES_`, `CLICKHOUSE_`, `IMBI_AUTH_`                   |
| `auth/core.py`       | JWT creation (`create_access_token`, `create_refresh_token`) and verification (`verify_token`)                                                                                                              |
| `auth/encryption.py` | Fernet symmetric encryption for sensitive tokens via `TokenEncryption` singleton; module-level `encrypt_token`/`decrypt_token` helpers                                                                      |
| `server.py`          | Typer/uvicorn `serve()` command and `bind_entrypoint()` helper for building service CLIs                                                                                                                    |
| `logging.py`         | Logging configuration loader using `log-config.toml`                                                                                                                                                        |
| `helpers.py`         | Small utility functions                                                                                                                                                                                     |

### Key patterns

**Singletons**: `Clickhouse.get_instance()`, `TokenEncryption.get_instance()`, and `settings.get_auth_settings()` all use class-level singletons. Tests that need clean state must reset them explicitly (e.g., `TokenEncryption.reset_instance()`). `Graph` is instantiated directly (no singleton).

**Graph + edges**: Models use `typing.Annotated` with `models.Edge(rel_type=..., direction=...)` metadata to declare graph relationships. `graph.py` uses `model_construct()` when deserializing raw node data from the graph so that missing edge fields do not cause validation errors.

**Blueprint system**: `blueprints.get_model(database, MyModel)` accepts a `Graph` instance and a model class, fetches `Blueprint` nodes from the graph whose `type` matches the model class name, then calls `pydantic.create_model` to return a dynamically extended subclass.

**Settings loading order**: Each `BaseSettings` subclass reads from `.env` file and environment variables with its prefix. `Configuration` additionally supports `config.toml` checked in order: `./config.toml` → `~/.config/imbi/config.toml` → `/etc/imbi/config.toml`.

**ClickHouse schema**: DDL is defined in `src/imbi_common/clickhouse/schemata.toml` and executed via `Clickhouse.setup_schema()` (called explicitly during setup, not on every startup).

**PostgreSQL schema**: Database init scripts live in `schema/postgres/` and are mounted into the Docker container's `/docker-entrypoint-initdb.d/`.

## Code style

- Line length: 79 characters
- Quote style: single quotes
- Type checking: strict (basedpyright + mypy)
- Test coverage minimum: 90%
- `ruff` rules include bandit (`S`), but `S` rules are disabled in test files
