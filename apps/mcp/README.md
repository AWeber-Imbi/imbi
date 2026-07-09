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

## Authentication

Two modes, which can be used together:

- **Token (always on).** The caller's `Authorization` header — an Imbi
  `ik_` API key or a JWT — is forwarded to the API, which authorizes the
  request. This works with no extra configuration.
- **OAuth (when configured).** Set `--public-url` and `--auth-server-url`
  (see below) to make the server an OAuth 2.0 Resource Server. It then
  verifies JWT access tokens locally, accepts-and-forwards `ik_` API
  keys, and publishes Protected Resource Metadata so MCP clients can
  discover the Imbi authorization server and run a browser login flow
  (authorization-code + PKCE, with Dynamic Client Registration). Local
  JWT verification uses the shared `IMBI_AUTH_JWT_SECRET`.

FastMCP's DNS-rebinding Host/Origin guard is opt-in (disabled by default as of
fastmcp 3.4.4), so requests arriving through a reverse proxy are accepted
normally. To enable it, set `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=true` and list
the public host(s) in `FASTMCP_HTTP_ALLOWED_HOSTS='["your-host"]'`.

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
| `--public-url`  | _(none)_                 | `IMBI_MCP_PUBLIC_URL` | Public base URL of the host fronting this server, WITHOUT the `/mcp` path (e.g. `https://host`); FastMCP appends its own `/mcp` mount path. Enables OAuth with `--auth-server-url` |
| `--auth-server-url` | _(none)_             | `IMBI_MCP_AUTH_SERVER_URL` | Imbi OAuth issuer URL (e.g. `https://host`); enables OAuth with `--public-url` |

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
