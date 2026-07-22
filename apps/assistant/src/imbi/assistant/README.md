# imbi-assistant

HTTP backend for the AI assistant embedded in the
[Imbi](https://github.com/AWeber-Imbi/imbi) DevOps service management
platform. It manages chat conversations and streams responses from
Anthropic's Claude over Server-Sent Events, giving Claude live access to
Imbi data and actions through tools.

## How It Works

The service exposes a small REST API for conversation CRUD plus a streaming
chat endpoint. When a user sends a message, the assistant:

1. Loads the conversation history from the graph and replays it to Claude.
2. Builds the tool set (see below) and a per-user
   [system prompt](src/imbi.assistant/system_prompt.md).
3. Streams Claude's response as SSE events, running any tool calls in a loop
   (up to `max_tool_rounds`) until Claude stops requesting tools.
4. Persists each assistant/tool-result round to the graph, and generates a
   short title for the first exchange.

The assistant's tools come from four sources, combined into a single list on
every turn:

- **Imbi API (OpenAPI).** At startup an in-process
  [FastMCP](https://github.com/jlowin/fastmcp) server is built from the Imbi
  API's `openapi.json` (auth/MFA/status/thumbnail routes excluded). The
  caller's bearer token is forwarded per request so API calls run with the
  user's permissions.
- **External MCP servers.** `MCPServer` nodes configured in the graph are
  connected over streamable HTTP; their tools are namespaced (`mcp_<prefix>_…`)
  and merged in. Supports static-header and OAuth client-credentials auth, with
  secrets decrypted at connect time. A bad server is logged and skipped, never
  fatal.
- **Client-side tools.** `navigate_to` and `refresh_data` don't run on the
  server — they emit a `client_action` SSE event the UI executes (browser
  navigation, cache invalidation after a mutation).
- **Refresh tool.** `refresh_openapi_spec` re-fetches the OpenAPI spec and
  reconnects every external MCP server mid-conversation, so newly deployed
  tools become available without a restart.

Conversations and messages are stored as nodes in the Apache AGE graph (via
`imbi-common`'s `Graph` client) and scoped to the authenticated user.

## Authentication

Every assistant endpoint requires a bearer JWT access token. Tokens are
verified locally using the shared `IMBI_AUTH_JWT_SECRET`; the subject is
looked up as a `User` node and its permissions resolved from the graph. The
same token is forwarded to the Imbi API when executing OpenAPI-backed tools.

## API

All routes are served under the path component of `IMBI_ASSISTANT_URL`
(e.g. `/assistant`), so they match the ingress prefix.

| Method   | Path                           | Description                              |
| -------- | ------------------------------ | ---------------------------------------- |
| `POST`   | `/conversations`               | Create a conversation                    |
| `GET`    | `/conversations`               | List the user's conversations            |
| `GET`    | `/conversations/{id}`          | Get a conversation with its messages     |
| `PATCH`  | `/conversations/{id}`          | Rename or archive a conversation         |
| `DELETE` | `/conversations/{id}`          | Delete a conversation and its messages   |
| `POST`   | `/conversations/{id}/messages` | Send a message; streams the reply as SSE |
| `GET`    | `/status`                      | Operational status (unprefixed)          |

## Requirements

- Python 3.14+
- A running [imbi-api](https://github.com/AWeber-Imbi/imbi-api) instance
- An Anthropic API key
- PostgreSQL with Apache AGE (shared with the rest of the Imbi stack)

## Quick Start

This project uses [uv](https://docs.astral.sh/uv/) for project management and
[just](https://just.systems/) as a task runner. Install both before
contributing.

```bash
just setup    # Sync dependencies and install pre-commit hooks
just serve    # Run the service in the foreground (reads .env)
just test     # Run the test suite
just lint     # Run ruff, basedpyright, and mypy
```

Run `just -l` for all available commands.

## Configuration

Settings are read from the environment (prefix `IMBI_ASSISTANT_`). The service
auto-enables when `ANTHROPIC_API_KEY` is present.

| Variable                                | Default                 | Description                                                       |
| --------------------------------------- | ----------------------- | ----------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`                     | _(none)_                | Anthropic API key; enables the assistant when set                 |
| `IMBI_ASSISTANT_ENABLED`                | `false`                 | Force-enable/disable independent of the API key                   |
| `IMBI_ASSISTANT_MODEL`                  | `claude-sonnet-4-6`     | Default model for new conversations                               |
| `IMBI_ASSISTANT_MAX_TOKENS`             | `16384`                 | Max output tokens per response                                    |
| `IMBI_ASSISTANT_MAX_TOOL_ROUNDS`        | `10`                    | Max tool-use rounds per message                                   |
| `IMBI_ASSISTANT_MAX_CONVERSATION_TURNS` | `100`                   | Max messages before a conversation is closed                      |
| `IMBI_ASSISTANT_SYSTEM_PROMPT`          | _(bundled template)_    | Override for the system prompt template                           |
| `IMBI_ASSISTANT_URL`                    | _(none)_                | Public URL; its path becomes the route prefix                     |
| `IMBI_INTERNAL_API_URL`                 | `http://localhost:8000` | In-cluster address of the Imbi API for service-to-service calls   |
| `IMBI_UI_URL`                           | _(none)_                | Public base URL of the Imbi UI, used to build deep links          |
| `IMBI_INTERNAL_UI_URL`                  | _(falls back to `IMBI_UI_URL`)_ | In-cluster UI address for fetching `llms.txt` (e.g. the Caddy frontend) |
| `IMBI_AUTH_JWT_SECRET`                  | _(required)_            | Shared secret for verifying access tokens (via `imbi-common`)     |
| `POSTGRES_URL`                          | _(required)_            | DSN for the AGE graph (via `imbi-common`)                         |

## Docker

```bash
docker build -t imbi-assistant .
docker run -p 8002:8002 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e IMBI_INTERNAL_API_URL=http://imbi-api:8000 \
  imbi-assistant
```

The image runs `imbi-assistant serve --host 0.0.0.0 --port 8002`.

## Code Formatting

Formatting is handled by automated tooling and is the sole authority on style:
**Ruff** for Python, **Tombi** for TOML, run via pre-commit hooks. Don't format
manually — use `just format` (optionally with a file path) and `just lint`.
