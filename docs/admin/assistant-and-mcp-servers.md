# Assistant and MCP Servers

Two admin pages configure the AI assistant (imbi-assistant):

| Page | What it configures | Scope |
|---|---|---|
| **Admin > Global Admin > Assistant** | The system prompt, the model, and the model parameters of the assistant | Every organization |
| **Admin > &lt;Org&gt; Admin > MCP Servers** | The external MCP servers. The assistant and the Slack bot use their tools | One organization |

An MCP server belongs to one organization. Its slug is unique in that
organization. Only the members of the organization see it.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py mcp_server: -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `mcp_server:create` | Create MCP servers | `admin` |
| `mcp_server:read` | View MCP servers | `admin` |
| `mcp_server:update` | Update MCP servers | `admin` |
| `mcp_server:delete` | Delete MCP servers | `admin` |
| `mcp_server:credential` | Get the secret values of MCP servers that use secret bindings | `admin`, `imbi-assistant`, `imbi-slackbot` |

<!-- END GENERATED -->

The API checks these permissions in the organization of the server.
`mcp_server:update` also lets you test a server. The **Assistant** page
uses the prompt permissions. See [Prompts](prompts.md).

## The assistant prompt

The **Assistant** page edits the prompt `imbi-assistant/system` in the
[prompt CMS](prompts.md). The prompt holds the system prompt, the model,
and the model parameters.

imbi-assistant reads the prompt from the reference in
`IMBI_ASSISTANT_PROMPT_REF` (default `imbi-assistant/system@stable`):

1. If the label in the reference exists, the assistant uses that version.
2. If not, the assistant uses the version of the default label of the
   prompt.
3. If neither label exists, the assistant uses its built-in prompt.

If the prompt does not exist, the page shows **Create assistant prompt**
(needs `prompt:create`). You can also run `imbi-api setup-prompts`. For
versions, labels, the environment override, and the model settings, see
[Prompts](prompts.md).

## MCP servers

An MCP server gives tools to the assistant and the
[Slack bot](../slackbot/index.md). A conversation uses only the enabled
servers of its organization: in the assistant, the organization of the
conversation; in Slack, the organization of the workspace. Each service
connects to the servers of an organization at the first message in that
organization. When you disable a server, both services stop using it at
the next message. After you add a server or change its settings, ask the
assistant to refresh its tools (the assistant only), or restart
imbi-slackbot.
Imbi connects to the server over streamable HTTP. The
tool names in the assistant are `mcp_<tool prefix>_<tool>`. If the
connection to a server fails, the next call to one of its tools opens
the connection again. If that attempt also fails, the assistant waits
60 seconds before it tries again. Agents do
not use these servers. See
[MCP servers and agents](#mcp-servers-and-agents).

### Add an MCP server

1. Select the organization, then open
   **Admin > &lt;Org&gt; Admin > MCP Servers**.
2. Click **Add MCP Server**.
3. Enter the fields in the tables below.
4. Optional: click **Test connection**.
5. Click **Create Server**.

**Identity**

| Field | What to enter |
|---|---|
| Display name | Required |
| Slug | Required. The default tool prefix |
| URL | Required. The streamable HTTP endpoint of the server |
| Description | Optional |
| Enabled | A disabled server is not used |

**Connection**

| Field | What to enter |
|---|---|
| Tool prefix | The prefix of the tool names in the assistant. Empty: the slug |
| Timeout | Seconds, from 1 to 300. The default is 30 |
| Verify SSL | On by default. Off accepts invalid certificates |

**Authentication**

| Auth type | Fields |
|---|---|
| None | No credentials. Use it only for an endpoint in a private network |
| Static header | **Header name** (for example `Authorization` or `X-Api-Key`) and **Header value**. Imbi sends the header on each request |
| OAuth client | **Token URL**, **Client ID**, **Client secret**, and **Scope** (optional, separated by spaces). Imbi gets a token with the OAuth 2.0 client credentials grant |

Imbi encrypts the header value and the client secret before it stores
them. The API never returns them. It returns only whether a value is set.
The assistant uses these stored values. See
[MCP servers and agents](#mcp-servers-and-agents).

The header value or the client secret can instead come from a secret
binding of the organization: select the binding as its source. The
binding must also list the server (see
[A binding for MCP servers](secrets.md#a-binding-for-mcp-servers)), and
imbi-assistant and imbi-slackbot must have their API tokens
(`IMBI_ASSISTANT_API_TOKEN`, `IMBI_SLACKBOT_API_TOKEN`). They get the
value from imbi-api each time they connect. **Test connection** works
only for a saved server that uses a binding. After you change the URL,
the token URL, the auth type, or **Verify SSL** of such a server, a user
with `secret_binding:write` must save the binding again before the
server can get the secret.

**Ignored tools**

Add a tool name to hide that tool. The list offers the tools that the
last connection test found.

### Status

Each server has a status: `unknown`, `healthy`, `degraded`, or
`unreachable`. **Test connection** connects to the server, lists its
tools, and saves the status, the latency, the tool count, and the error.
The **With issues** filter shows the servers that are `degraded` or
`unreachable`.

### Servers made before organizations

Before servers belonged to an organization, they were global. When
imbi-api starts and the install has one organization, it moves each of
these servers to that organization. When the install has more than one
organization, imbi-api does not move them and logs a warning for each.
No organization shows such a server. Create it again in the correct
organization.

## MCP servers and agents

These servers are for the assistant and the Slack bot only. Agents do
not use them. An
agent gets MCP servers from the plugins of its marketplaces. See
[Agents](agents.md).

## Related pages

- [Prompts](prompts.md)
- [Agents](agents.md)
- [Secrets](secrets.md)
- [Assistant](../assistant/index.md)
- [MCP](../mcp/index.md)
