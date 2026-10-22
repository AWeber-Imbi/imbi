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

`mcp_server:update` also lets you test a server. Only a platform
administrator can set the **Credential reference** of a server or link a
credential for agents. The **Prompt** tab uses the prompt permissions. See
[Prompts](prompts.md).

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
The assistant uses these stored values. Agents do not. See
[Credentials for agents](#credentials-for-agents).

**Ignored tools**

Add a tool name to hide that tool. The list offers the tools that the
last connection test found.

### Status

Each server has a status: `unknown`, `healthy`, `degraded`, or
`unreachable`. **Test connection** connects to the server, lists its
tools, and saves the status, the latency, the tool count, and the error.
The **With issues** filter shows the servers that are `degraded` or
`unreachable`.

## Credentials for agents

An agent never uses the encrypted header value or client secret. The
runner gets the credential from the [secrets broker](secrets.md) with the
**Credential reference** of the server, for example
`secret://mcp/github#token`. The reference applies in every
organization: each organization that uses the server needs a binding for
the same reference.

An agent can use a server only when all of these are true:

- The server is enabled.
- The URL uses `https` and **Verify SSL** is on.
- For a server with authentication: the server has a credential
  reference, and a grant gives the agent that reference with the purpose
  `mcp_server` and the delivery mode `file_descriptor`.

Otherwise the runner leaves out the server, with a reason such as
`server_disabled`, `tls_required`, or `no_credential_ref`.

### Link a credential

The **Link credential for agents** button makes the binding and the grant
in one step. It works in the organization that you select in the top
bar. You must be a platform administrator and a member of that
organization.

1. Put the credential value in the secret store of the organization, for
   example AWS Secrets Manager. The binding holds no secret.
2. Open the server.
3. Under **Agent credential**, click **Link credential for agents**.
4. Enter the fields in the table below.
5. Submit the dialog.

| Field | What to enter |
|---|---|
| Reference | `secret://<scope>/<path>`, lowercase, with no field |
| Field | The field of the secret that holds the value. Empty: the whole value |
| Provider | The secret provider of the organization |
| Locator | Where the provider finds the secret, as JSON. For AWS: `{"secret_id": "prod/app", "version_stage": "AWSCURRENT"}` |
| Agents | The agents that can use the credential. Empty: Imbi makes no grant |
| Maximum TTL (seconds) | The default is 900 |

Imbi then does these steps:

1. It makes a `static` binding that allows only `file_descriptor`
   delivery.
2. If you selected agents, it makes a grant with the purpose `mcp_server`
   for them.
3. It asks the provider if the secret exists. If not, it removes what it
   made and returns `422 credential_binding_not_valid`.
4. It sets the **Credential reference** of the server.

If the server already has a different reference, Imbi refuses with `409
credential_ref_conflict`. To change the reference, edit the **Credential
reference** field.

To add more agents later, add a grant on the **Secrets** page. See
[Add a grant](secrets.md#add-a-grant).

## Related pages

- [Prompts](prompts.md)
- [Agents](agents.md)
- [Secrets](secrets.md)
- [Assistant](../assistant/index.md)
- [MCP](../mcp/index.md)
