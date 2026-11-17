# ADR 0030: Plugin MCP Server Credentials

Date: 2026-11-17

## Status

Proposed

Related: [ADR 0022](0022-agent-harness-and-secrets-broker.md) (harness,
plugins, and secrets broker). This ADR adds one secret purpose and one
runner relay to that design. [ADR 0029](0029-automations.md)
(automations) is out of scope. The Scope section below explains why.

## Context

An agent gets MCP servers only from the plugins of its marketplaces. A
plugin declares a server in its marketplace entry, in its
`.claude-plugin/plugin.json`, or in its `.mcp.json`. Many servers need a
credential in an HTTP header, for example:

```json
"logzio": {
  "type": "http",
  "url": "https://api.logz.io/mcp",
  "headers": {"X-API-TOKEN": "${LOGZIO_API_TOKEN}"}
}
```

Claude Code (the CLI) fills `${LOGZIO_API_TOKEN}` from its own
environment. The harness puts no secret in that environment, because
the model's `Bash` inherits it. So the server gets no valid token.
Depending on the server, the CLI reports it as `needs-auth` or `failed`,
or it connects and lists tools whose calls then fail.

An agent can have a secret binding for the token, but the harness
delivers a binding only to `run_with_secret` commands. The failure is
also hidden. The harness logs the server statuses from the SDK `init`
message, but shows nothing in the task.

There are three other gaps:

- The Tools and plugins section of an agent lists a plugin's servers
  only when the marketplace entry declares them inline. The marketplace
  sync does not read a plugin's own `plugin.json` or `.mcp.json`.
- An agent cannot turn off one server of a plugin while it keeps the
  plugin for another reason, such as a skill. This matters when two
  enabled plugins declare a server with the same URL.
- The egress proxy cannot add a header, because the CLI's HTTPS
  requests pass through the proxy inside a `CONNECT` tunnel.

Until [#608](https://github.com/AWeber-Imbi/imbi/pull/608) (commit
`50c3424c`), the harness relayed third-party MCP servers, the MCP
servers of Admin > Assistant. #608 removed that relay because agents
then had two sources of MCP servers, and the admin servers were never
meant for agents. Commit `8e3ad1de` then retired `mcp_server`, the
broker purpose of that relay. The admin servers stay assistant-only.
This ADR relays the servers that plugins declare, which is the one
source that #608 kept. The removed relay code (`start_external`, the
credential fetch, the warnings) is a starting point for the
implementation.

## Decision

The runner holds the credential and connects to the server. The CLI
does not. The runner then offers the server's tools to the CLI under
the names the CLI would give them if it connected to the plugin's
server itself. This ADR calls that part of the runner the relay. A
relayed server is an enabled server with at least one secret.

### Scope

This decision covers only `${VAR}` and `${VAR:-default}` in the
`headers` values of an `http` or `sse` server. It does not cover
`headersHelper`, the `env` of a `stdio` server, `${VAR}` in a URL, or
OAuth. OAuth needs a person, and these agents run without one.

It covers agent tasks that the harness runs with `run_sdk`. It does not
cover:

- The `claude` actions of automations (ADR 0029). They run the engine's
  own model session, so neither the relay nor the `PreToolUse` hook
  applies. The work on automations must decide how they get relayed
  servers.
- Child tasks. Today only the root task of a chain clones and loads
  plugins, so a child task has no plugin servers at all. That gap is
  separate from this ADR
  ([#772](https://github.com/AWeber-Imbi/imbi/issues/772)).

### The marketplace sync reads the servers the harness loads

The sync finds a plugin's MCP servers with the same rule that the
harness uses when it publishes the plugin (`_manifest` and
`_plugin_servers`):

- If the plugin directory has `.claude-plugin/plugin.json`, the servers
  are its `mcpServers` and those of `.mcp.json`. `mcpServers` is an
  object, the path of a JSON file, or a list of both. The sync ignores
  the marketplace entry's `mcpServers`, because they do not reach the
  CLI in this case.
- If it has no `plugin.json`, the marketplace entry is the manifest.
  The servers are the entry's `mcpServers` and those of `.mcp.json`.
- Tool names use the manifest's `name` as the plugin name.

The sync reads these files with the `RepositoryReader` that reads
`marketplace.json`. For a plugin stored in the marketplace repository,
it reads them at the marketplace head SHA. For an external plugin, it
reads them at the plugin's `repository_sha`. If a file cannot be read,
the sync lists no servers from it and does not fail. The scheduler
runs the sync every 6 hours, so the extra reads are small next to the
GitHub rate limit.

For each server, the sync stores the name, the type, the URL, and the
header names, with the variables that each header uses. It stores no
header value, because a plugin author can commit a literal token there.

`CatalogPlugin.mcp_servers` changes from a list of names to a list of
these objects. A validator reads both shapes, so a stored catalog stays
valid until its next sync.

### Agent configuration

`AgentPlugin` gets a new field, `mcp_servers`. It holds one entry for
each server that the agent changes from the default:

| Field     | Content                                                          |
| --------- | ---------------------------------------------------------------- |
| `name`    | The server name in the plugin                                    |
| `enabled` | `false` turns the server off. Default `true`                     |
| `secrets` | A map of header variable to secret reference                     |
| `origin`  | The scheme, host, and port of the server URL. Set with `secrets` |

A server with no entry is on and has no secrets, so the CLI connects to
it as it does today. Existing agents need no migration. The entries are
part of the agent version, like the plugin pin.

The API:

- Keeps the request's `mcp_servers` when it pins plugins. Today
  `pin_plugins` keeps the stored entry whenever the `sha` matches, and
  `_pin` copies five fields. Both must carry `mcp_servers`.
- Checks each secret reference with `check_reference`, and each server
  and variable name against the plugin's servers.
- Requires an `https` origin for a server with secrets.
- Refuses `mcp_servers` on the organization's `default_plugins`.

The Tools and plugins section lists each server under its plugin,
indented, with its own checkbox. Under a checked server, it shows the
server URL and lists each header variable next to a picker for a secret
reference. Unchecking a plugin turns off all of its servers. The UI
keeps `mcp_servers` when it re-pins or toggles a plugin.

The code does not detect duplicate servers. To remove a duplicate, a
person unchecks one of the two.

A default plugin keeps its locked checkbox, but its server checkboxes
and secret pickers work. The merge of the agent configuration applies
the agent's `mcp_servers` entries to the default plugin with the same
marketplace and name.

When a person picks a secret for a server whose URL origin later
changes, the UI shows the new URL and asks for the secret again.

The catalog holds the servers of the newest commit, but an agent
version runs the commit it pinned. So the UI marks each of an agent's
server entries that the newest commit does not have, as it already
marks a stale plugin pin.

### Secret purpose and grants

A new runner-only purpose, `mcp_header`, joins:

- `SETUP_PURPOSES` in the broker
- `SETUP_PURPOSES` in the harness task, which `_secret_refusal` uses
- `SETUP_PURPOSES` and `FETCH_PURPOSES` in the executor. The executor's
  `fetch` checks `FETCH_PURPOSES`.
- the purpose list of the UI and the purpose table of the docs

`mcp_server` stays retired. Like the other setup purposes, a grant for
`mcp_header` can use only the `file_descriptor` delivery mode, so a
model command can never receive it. A `run_with_secret` grant uses the
`environment` delivery mode, so the two purposes are always in separate
grants. A binding can have both grants, and then the model can also use
the token in a command.

When a person picks a secret for a header variable, the Tools and
plugins section:

1. Checks that the binding allows the delivery mode `file_descriptor`
   and the target `3`. If not, it shows that the binding cannot be
   used here.
2. Does nothing more if a grant already covers the agent, the binding,
   `mcp_header`, and `file_descriptor`. A second matching grant would
   make the broker refuse with `ambiguous_grants`.
3. Otherwise adds `mcp_header` to the agent's own `file_descriptor`
   grant for that binding, or creates that grant, as the Access tab
   does today.

These steps need `secret_binding:read` and `secret_grant:write`.
Without them, the section shows that a grant is missing. A grant
applies at once and is not part of the agent version.

### Runner relay

When the runner builds the workspace, it:

1. Computes `plugin_servers`, the permission rules for plugin servers,
   from the published plugin copies before it changes them. The rules
   keep each relayed server and leave out each turned-off server. So
   the allowed tools and the tool policy treat relayed tools as plugin
   tools.
2. Removes each turned-off server and each relayed server from the
   plugin copy under `/run/plugins`. Root owns the copy, so the model
   cannot add a server back.
3. Checks the agent's entries against the pinned copy. An entry for a
   server or a variable that the copy does not have gets a warning.

For each relayed server, the runner:

1. Checks that the server URL is `https` and that its origin equals the
   `origin` of the entry. If not, it does not relay the server and adds
   a warning.
2. Resolves each secret once, with the purpose `mcp_header`. The
   executor passes the value to the runner, as it does for the model
   key. A credential with an expiry is refreshed before it expires, as
   the model key is. The runner refuses a value that is not a string,
   such as a whole JSON secret without `#field`, and adds a warning.
3. Fills the headers. It leaves out a header whose variable has no
   secret and no default.
4. Opens an MCP client session to the server URL. The client uses the
   runner's egress proxy settings (`HTTPS_PROXY` with the chain token,
   and `NO_PROXY`), or connects directly when there is no proxy. The
   client follows a redirect only to the same origin.
5. Gives the CLI an in-process server, an `mcp.server.Server` passed to
   the SDK as `instance`. Its name is `plugin:<plugin>:<server>`, the
   name the CLI gives the plugin's own server. The CLI names its tools
   `mcp__plugin_<plugin>_<server>__<tool>`, with each character outside
   `[A-Za-z0-9_-]` replaced by `_`. So the relayed tools have the same
   names as the tools of the plugin's own server, and the relayed
   server has the same name in the server statuses.

The relay forwards tools, resources, and prompts. Each call gets the
same safeguards as in the Imbi relay, the relay for Imbi's own MCP
server. A call has a timeout, ends when the task stops, and has a limit
on result size. Its result goes to the model in `<untrusted>` tags. The
relay also removes each secret value from the result, in case the
server echoes a request header.

The relay's server never ends on an upstream error, because the SDK
does not restart an in-process server that ends. The relay returns the
error as the result of the call instead.

The relay keeps one session per server for the life of the task. It
opens the session again after a connection error, for example when the
server closes an idle session. When it refreshes a credential with an
expiry, it opens the session again with the new headers before the old
credential expires. A static secret is not resolved again, so a revoked
grant takes effect at the next task.

The SDK bridge to an in-process server has these limits:

- It drops server notifications, such as progress, logging, and
  `tools/list_changed`. The CLI's tool list is fixed after its first
  `tools/list`.
- It refuses a request that a server sends to its client, such as
  sampling, elicitation, or roots.
- With mcp 1.x, it does not pass a cancellation to a hand-built server.
  Until mcp 2.x, the relay's call timeout limits how long such a call
  runs.

The model's `Bash` cannot reach the relay, because the CLI talks to the
relay over the SDK control channel and not over a socket. Every call to
the relay goes through the `PreToolUse` hook.

### Server problems show as task warnings

The runner adds a task warning with `recorder.notice` in each case
below, and the Conversation tab shows it. No warning fails the task.

- A plugin server's status is `failed` or `needs-auth`. A remote
  server is often still `pending` in the SDK `init` message, so the
  runner reads the statuses again with the SDK's `get_mcp_status` until
  no server is `pending` or a short wait ends. A server still `pending`
  then gets a warning too.
- The upstream server refuses the relay's session.
- An enabled server has a header variable with no secret and no
  default. The warning names the variable. The server starts anyway,
  and its status or its failed calls show the result.
- An entry names a server or variable that the pinned copy does not
  have.
- A relayed server's URL is not `https`, or its origin changed.
- A secret value is not a string.

### Verified CLI behavior

These are Claude Code behaviors, not code in this repository. They were
checked with Claude Agent SDK 0.2.164 and Claude Code 2.1.292:

- An in-process server named `plugin:<plugin>:<server>` or
  `plugin_<plugin>_<server>` gets the tool names
  `mcp__plugin_<plugin>_<server>__<tool>`. Its status uses the name it
  was given.
- When two plugins declare a server with the same URL, the CLI loads
  only the server of the first plugin.
- The `init` message reports an `http` plugin server as `pending`. The
  status changes later.

## Consequences

- A header credential stays in the runner's memory. It is never in the
  CLI's environment, a plugin file, or a model command, unless a person
  also grants it for `run_with_secret`.
- A credential goes only to the origin that a person saw when they
  picked the secret. A plugin update that moves the server to another
  origin stops the relay until a person confirms the new URL.
- An agent can turn off any server of a plugin, including a default
  plugin, and keep the plugin's skills, hooks, and commands.
- A person can see every server of a plugin before enabling it.
- Results of relayed servers reach the model in `<untrusted>` tags.
  Results of a plugin server that the CLI connects to itself do not.
- A revoked grant does not stop a running task.
- The CLI does not know a relayed server's URL, so two relayed servers
  with the same URL both load. Only the checkboxes prevent this.
- A server that needs `headersHelper`, OAuth, or a URL variable still
  does not work in an agent. Its status now shows in the task.
- Each relayed server holds a session in the runner for the life of the
  task.

## Alternatives Considered

### Put the secret in the CLI's environment

Refused. The model's `Bash` inherits that environment and can print the
token.

### Add the header in the egress proxy

Refused. The proxy sees only a `CONNECT` tunnel. Adding a header needs
TLS interception and a CA that the CLI trusts.

### A loopback HTTP forwarder in the runner

The runner rewrites the plugin's server URL to a loopback port, and adds
the header to each request that arrives there. The CLI sends its MCP
requests to the rewritten URL as before.

Refused. The model's `Bash` can reach loopback and can read the
rewritten URL from the plugin copy. It can then send `tools/call` to the
forwarder, which adds the token, and the call skips the `PreToolUse`
check.

### Use the Admin > Assistant MCP servers for agents

The admin form already has a header name, an encrypted value, and
OAuth client credentials.

Refused. #608 removed this path. The credential is one global value
outside the secrets broker, with no grant or audit per agent. Agents
would also ignore the server declarations of the plugins.

### One MCP session per tool call

The relay would open a new session for each call, as the Imbi relay
does, so a renewed token would apply at once.

Not chosen. A third-party session costs a handshake for each call, and
some servers keep state in a session. A static secret is resolved once
per task. A credential with an expiry is refreshed on a known schedule,
and the relay opens a new session when it refreshes one. So a new
session for each call adds nothing.

### Resolve the secrets again on a fixed interval

Not chosen. Each resolution is a broker call and an audit event. The
only gain is that a revoked grant stops a running task sooner. The
clone and marketplace tokens do not do this either.

### Detect duplicate servers in code

Refused. Two plugins can declare one URL with different headers. The
checkboxes let a person keep the one they want.
