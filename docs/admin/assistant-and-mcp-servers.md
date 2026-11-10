# Assistant and MCP Servers

**Admin > Global Admin > Assistant** configures the AI assistant
(imbi-assistant) and the external MCP servers. The **Admin** item shows
only for platform administrators. The page has two tabs:

| Tab | What it configures |
|---|---|
| **MCP Servers** | The external MCP servers. The assistant and the agents use their tools |
| **Prompt** | The system prompt, the model, and the model parameters of the assistant |

These settings are global. They apply to every organization.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py mcp_server: -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `mcp_server:create` | Create MCP servers | `admin` |
| `mcp_server:read` | View MCP servers | `admin` |
| `mcp_server:update` | Update MCP servers | `admin` |
| `mcp_server:delete` | Delete MCP servers | `admin` |

<!-- END GENERATED -->

`mcp_server:update` also lets you test a server. The **Prompt** tab uses
the prompt permissions. See [Prompts](prompts.md).

## The assistant prompt

The **Prompt** tab edits the prompt `imbi-assistant/system` in the
[prompt CMS](prompts.md). The prompt holds the system prompt, the model,
and the model parameters.

imbi-assistant reads the prompt from the reference in
`IMBI_ASSISTANT_PROMPT_REF` (default `imbi-assistant/system@stable`):

1. If the label in the reference exists, the assistant uses that version.
2. If not, the assistant uses the version of the default label of the
   prompt.
3. If neither label exists, the assistant uses its built-in prompt.

If the prompt does not exist, the tab shows **Create assistant prompt**
(needs `prompt:create`). You can also run `imbi-api setup-prompts`. For
versions, labels, the environment override, and the model settings, see
[Prompts](prompts.md).

## MCP servers

An MCP server gives tools to the assistant and to the agents. Imbi
connects to the server over streamable HTTP.

| Who | Which servers | Tool names |
|---|---|---|
| imbi-assistant | Every enabled server | `mcp_<tool prefix>_<tool>` |
| Agents | The servers of the tools that the agent has. See [Agents](agents.md#tools-and-plugins) | `<server slug>.<tool>` |

### Add an MCP server

1. Open **Admin > Global Admin > Assistant**.
2. On the **MCP Servers** tab, click **Add MCP Server**.
3. Enter the fields in the tables below.
4. Optional: click **Test connection**.
5. Click **Create Server**.

**Identity**

| Field | What to enter |
|---|---|
| Display name | Required |
| Slug | Required. Agent tool keys use the slug |
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

**Ignored tools**

Add a tool name to hide that tool. The list offers the tools that the
last connection test found.

### Status

Each server has a status: `unknown`, `healthy`, `degraded`, or
`unreachable`. **Test connection** connects to the server, lists its
tools, and saves the status, the latency, the tool count, and the error.
The **With issues** filter shows the servers that are `degraded` or
`unreachable`.

## MCP servers and agents

These servers are for the assistant only. Agents do not use them. An
agent gets MCP servers from the plugins of its marketplaces. See
[Agents](agents.md).

## Related pages

- [Prompts](prompts.md)
- [Agents](agents.md)
- [Secrets](secrets.md)
- [Assistant](../assistant/index.md)
- [MCP](../mcp/index.md)
