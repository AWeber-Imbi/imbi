# MCP Server

`imbi-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io/)
server. It gives an AI client, for example Claude Code, the Imbi API as a set
of tools. The client acts as you: each tool call uses your credential, and
imbi-api applies your permissions.

The server runs on port 8001 and uses the streamable HTTP transport. The
all-in-one image serves it at `https://<imbi host>/mcp`.

## Tools

At startup, imbi-mcp reads the OpenAPI spec of imbi-api and makes one tool
for each operation. These operations are not tools:

- the auth, MFA, and status routes, and the thumbnail routes
- each operation that imbi-api marks as not for AI, for example project
  configuration values

Each tool has MCP annotations. A `GET` tool is read only. A `DELETE` tool is
destructive.

imbi-mcp reads the spec one time. When imbi-api adds or changes an
operation, restart imbi-mcp. When imbi-api is not reachable at startup,
imbi-mcp does not start.

### Tools are filtered for each caller

`tools/list` shows only the tools that you can call:

1. imbi-mcp gets your profile from imbi-api (`/users/me`) with your
   credential. For a service account, it gets `/users/me/permissions`.
2. It keeps each tool whose required permissions you hold. An admin gets
   all the tools. A tool that only an admin can call is hidden from all
   other callers.
3. It keeps the result for 60 seconds for each credential. A role change
   shows within that time.

The filter is advisory. imbi-api is the only enforcement point.

- When imbi-mcp cannot get your profile, it shows all the tools.
- The profile has your permissions in all your organizations. A call in one
  organization can still get `403`, because imbi-api uses your role in that
  organization.

## Authentication

imbi-mcp sends your `Authorization` header to imbi-api with each call. It
has two modes.

| Mode | When | What happens |
|---|---|---|
| Pass-through | `IMBI_MCP_PUBLIC_URL` or `IMBI_MCP_AUTH_SERVER_URL` is not set | imbi-mcp does not check the token. imbi-api checks it on each call. The client must send a bearer token |
| OAuth | Both are set | imbi-mcp is an OAuth 2.0 resource server. It checks the token, and a client can sign in through the browser |

In OAuth mode, imbi-mcp accepts these tokens:

- An Imbi access token (a JWT). imbi-mcp verifies it with
  `IMBI_AUTH_JWT_SECRET`.
- An `ik_` API key. imbi-mcp cannot verify it, so it sends it to imbi-api.
- An agent API token, from an agent runner.

For another token, imbi-mcp returns `401` with a `WWW-Authenticate`
challenge. That starts OAuth discovery in the client.

### OAuth discovery

1. The client calls `/mcp` and gets `401`.
2. The client reads the protected resource metadata from imbi-mcp, under
   `/.well-known/oauth-protected-resource`. It names Imbi as the
   authorization server.
3. The client reads the authorization server metadata from imbi-api at
   `/.well-known/oauth-authorization-server`. The proxy also serves it at
   `/mcp/.well-known/oauth-authorization-server`.
4. The client registers itself with dynamic client registration. Imbi
   registers public clients only.
5. The client opens the browser. You sign in to Imbi, when you are not
   signed in already.
6. The client gets a token with the authorization code flow and PKCE
   (`S256`). The scope is `imbi`.

The authorization code flow needs Valkey. When imbi-api has no Valkey, the
authorize step returns `503`.

## Connect a client

### Claude Code with OAuth

1. Run this command:

    ```shell
    claude mcp add --transport http imbi https://imbi.example.com/mcp
    ```

2. In Claude Code, run `/mcp`, select `imbi`, and authenticate. Claude Code
   opens the browser.

### Claude Code with an API key

Use this when OAuth mode is off, or for a script.

1. Make an API key. See [Your Settings](../user-guide/settings.md).
2. Run this command:

    ```shell
    claude mcp add --transport http imbi https://imbi.example.com/mcp \
      --header "Authorization: Bearer ik_..."
    ```

The tools act with the permissions of the API key.

### Other clients

Give the client the URL `https://<imbi host>/mcp` and the streamable HTTP
transport. If the client supports OAuth, it finds the sign-in flow by
itself. If not, give it the header `Authorization: Bearer <API key>`.

The assistant and the Slack bot do not use imbi-mcp. Each builds the same
tools in its own process.

## Settings

The full list is in [Configuration](../api/configuration.md).

| Variable | Default | What it is |
|---|---|---|
| `IMBI_INTERNAL_API_URL` | `http://localhost:8000` | Where imbi-mcp connects to imbi-api |
| `IMBI_MCP_PUBLIC_URL` | none | The public URL of the host, **without** `/mcp`, for example `https://imbi.example.com`. imbi-mcp adds `/mcp`. A value with `/mcp` breaks discovery |
| `IMBI_MCP_AUTH_SERVER_URL` | none | The Imbi OAuth issuer, for example `https://imbi.example.com` |
| `IMBI_AUTH_JWT_SECRET` | none | Verifies access tokens in OAuth mode. Use the same value as imbi-api |

The `imbi-mcp serve` command also takes `--transport` (`stdio`, `http`,
`sse`, or `streamable-http`), `--host`, and `--port`.

## Endpoints

| Path | What it is |
|---|---|
| `/mcp` | The MCP endpoint |
| `/.well-known/oauth-protected-resource*` | Protected resource metadata, in OAuth mode |
| `/status` | The health check. It needs no token |

To show imbi-mcp in the **System health** card of the Admin overview, set
`IMBI_INTERNAL_MCP_URL` on imbi-api, for example `http://imbi-mcp:8001`.
