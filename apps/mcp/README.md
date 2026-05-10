# imbi-mcp

MCP server for the [Imbi](https://github.com/AWeber-Imbi/imbi) DevOps service
management platform. Exposes Imbi API functionality to AI agents via the
[Model Context Protocol](https://modelcontextprotocol.io/).

## How It Works

At startup the server fetches the OpenAPI spec from a running
[imbi-api](https://github.com/AWeber-Imbi/imbi-api) instance and
auto-generates MCP tools, resources, and resource templates using
[FastMCP](https://github.com/jlowin/fastmcp).

Route mapping rules control what gets exposed:

- **Excluded** -- Auth, MFA, status, and thumbnail endpoints are hidden.
- **Resources** -- `GET` endpoints that return collections.
- **Resource templates** -- `GET` endpoints with path parameters.
- **Tools** -- Everything else (create, update, delete operations).

The caller's `Authorization` header is forwarded to the API so that
requests run with the caller's permissions.

## Requirements

- Python 3.12+
- A running imbi-api instance

## Quick Start

```bash
# Install dependencies
just setup

# Run the server (imbi-api must be reachable)
just serve

# Or with explicit options
imbi-mcp serve --api-url http://localhost:8000 --transport streamable-http
```

## CLI Options

```
imbi-mcp serve [OPTIONS]
```

| Option          | Default                  | Env Var        | Description              |
| --------------- | ------------------------ | -------------- | ------------------------ |
| `--api-url`     | `http://localhost:8000`  | `IMBI_INTERNAL_API_URL` | Base URL of the Imbi API |
| `--transport`   | `streamable-http`        |                | MCP transport type       |
| `--host`        | `127.0.0.1`              |                | Host to bind to          |
| `--port`        | `8001`                   |                | Port to bind to          |

Supported transports: `stdio`, `http`, `sse`, `streamable-http`

## Docker

```bash
docker build -t imbi-mcp .
docker run -p 8001:8001 -e IMBI_INTERNAL_API_URL=http://imbi-api:8000 imbi-mcp
```

## Development

```bash
just setup       # Install deps and pre-commit hooks
just test        # Run tests (90% coverage minimum)
just lint        # Run ruff, basedpyright, mypy
just format      # Auto-format code
```

## License

BSD-3-Clause
