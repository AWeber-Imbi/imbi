# Agent Instructions for imbi-assistant

## Project Overview

imbi-assistant is the HTTP backend for the AI assistant embedded in the Imbi
DevOps service management platform. It manages chat conversations and streams
responses from Anthropic's Claude over Server-Sent Events (SSE), giving Claude
live access to Imbi data and actions through tools. See `README.md` for the
user-facing overview.

## Architecture

```
imbi-ui ──HTTP/SSE──► imbi-assistant ──► Anthropic Claude
                            │
                            ├─ imbi-api OpenAPI tools (in-process FastMCP)
                            ├─ external MCP servers (streamable HTTP)
                            ├─ client-side tools (navigate_to, refresh_data)
                            └─ AGE graph (conversations, messages, MCPServer nodes)
```

- `src/imbi_assistant/app.py` -- `create_app()` wires the FastAPI app and its
  lifespans (Sentry, graph, Anthropic client, OpenAPI MCP, external MCP). Typer
  `serve` CLI entry point.
- `src/imbi_assistant/endpoints.py` -- Conversation CRUD and the SSE streaming
  chat endpoint. `_stream_response` runs the tool-use loop: stream a turn,
  dispatch any tool calls, persist the round, repeat up to `max_tool_rounds`.
- `src/imbi_assistant/mcp.py` -- `MCPManager`: builds an in-process FastMCP
  server from imbi-api's `openapi.json` and exposes its operations as Anthropic
  tools. Forwards the caller's bearer token per request.
- `src/imbi_assistant/external_mcp.py` -- `ExternalMCPManager`: connects to
  `MCPServer` graph nodes over streamable HTTP, namespaces their tools
  (`mcp_<prefix>_…`), and supports static-header and OAuth client-credentials
  auth (secrets decrypted at connect time).
- `src/imbi_assistant/client_tools.py` -- `navigate_to` / `refresh_data`. These
  execute in the browser; the backend emits a `client_action` SSE event instead
  of running them server-side.
- `src/imbi_assistant/age_ops.py` -- Cypher/AGE persistence for conversations
  and messages, plus reading enabled MCP server nodes.
- `src/imbi_assistant/auth.py` -- JWT bearer verification and per-user
  permission resolution from the graph.
- `src/imbi_assistant/system_prompt.py` + `system_prompt.md` -- Builds the
  per-user system prompt from the bundled template (override via
  `IMBI_ASSISTANT_SYSTEM_PROMPT`).
- `src/imbi_assistant/settings.py` -- `IMBI_ASSISTANT_`-prefixed settings.

## Key Design Decisions

- **Four tool sources, one list.** Every turn combines OpenAPI tools, external
  MCP tools, client-side tools, and the `refresh_openapi_spec` server tool. The
  refresh tool rebuilds both the OpenAPI and external MCP sources mid-conversation.
- **Fail-soft startup.** A graph or external-MCP failure at startup must not stop
  the service: a bad external server is logged and skipped, and an empty manager
  is installed so request handling never 500s.
- **Tool-round persistence is atomic.** `_persist_tool_round` writes the
  assistant `tool_use` message and its matching `tool_result` user message under
  `asyncio.shield`. Anthropic rejects a conversation where a `tool_use` is not
  immediately followed by a `tool_result`, so a client disconnect between the two
  writes would permanently break the conversation.
- **Tool errors must surface.** Tool executors return `(content, is_error)`; the
  Anthropic API only treats a result as a failure when `is_error: true` is set,
  letting Claude correct its inputs.
- **Auth is per-request.** The caller's token is injected into the OpenAPI HTTP
  client only for the duration of a tool call, then cleared, so API calls run
  with the user's permissions.

## Code Standards

- **Line length**: 79 characters
- **Quotes**: Single quotes for strings
- **Type checking**: basedpyright strict mode + mypy strict mode
- **Testing**: `unittest` (`IsolatedAsyncioTestCase`), 90% minimum coverage
- **Logging**: Use `%s` formatting, not f-strings
- **Async**: All I/O in production code must be async

Do not format code manually — Ruff (Python) and Tombi (TOML) via pre-commit
hooks are the sole authority on style. Use `just format` and `just lint`.

## Development Commands

```bash
just setup       # Sync dependencies and install pre-commit hooks
just serve       # Run the service in the foreground (reads .env)
just test        # Run pytest with coverage
just lint        # Run pre-commit, basedpyright, mypy
just format      # Auto-format with ruff and tombi
```

Run `just -l` for the full list.

## Testing

Tests use `unittest.IsolatedAsyncioTestCase`; external I/O (Anthropic, httpx,
MCP sessions, the graph) is mocked. `tests/helpers.py` provides a base
`TestCase` and an `override_environment` context manager.

```bash
uv run pytest                         # Run all tests
uv run pytest tests/test_endpoints.py # Run a specific test file
```

## CI/CD

GitHub Actions (`.github/workflows/test.yml`) runs on push/PR to `main`:

- **Static Analysis**: `just lint` (pre-commit + basedpyright + mypy)
- **Automated Tests**: `just test` on Python 3.14, with coverage uploaded to
  Codecov

## Dependencies

- **anthropic** -- Claude API client
- **fastapi** -- HTTP framework and SSE streaming
- **fastmcp** -- In-process MCP server built from the OpenAPI spec
- **mcp** -- Client for external streamable-HTTP MCP servers
- **httpx** -- Async HTTP client
- **imbi-common** -- Shared models, graph client, auth, settings (installed
  from git)

Manage dependencies with `uv`. After changing `pyproject.toml`, run `uv lock`
to update the lock file.
