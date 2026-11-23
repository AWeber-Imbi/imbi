# ADR 0031: Plugin MCP Server Credentials

Date: 2026-11-17

## Status

Accepted

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
source that #608 kept.

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

It covers agent tasks that the harness runs with `run_sdk`, child
tasks included. Each task of a chain loads its own pinned plugins, so
the relay lives in the task and a child task gets it too. It does not
cover the `claude` actions of automations (ADR 0029). They run the
engine's own model session, so neither the relay nor the `PreToolUse`
hook applies. The work on automations must decide how they get relayed
servers.

### The marketplace sync reads the servers the harness loads

The sync finds a plugin's MCP servers with the rule the harness uses
when it publishes the plugin. If the plugin has a
`.claude-plugin/plugin.json`, the servers come from it and from
`.mcp.json`. Otherwise they come from the marketplace entry and from
`.mcp.json`. A file the sync cannot read adds no servers and does not
fail the sync.

For each server, the sync stores the name, the type, the URL, and the
header names, with the variables that each header uses. It stores no
header value, because a plugin author can commit a literal token there.

### Agent configuration

`AgentPlugin` gets a new field, `mcp_servers`, with one entry for each
server that the agent changes from the default. An entry can turn the
server off, or map its header variables to secret references. An entry
with secrets also records the origin of the server URL that the person
saw when they picked the secrets, and the origin must be `https`. A
server with no entry is on and has no secrets, so the CLI connects to
it as it does today, and existing agents need no migration. The
entries are part of the agent version, like the plugin pin.

The Tools and plugins section lists each server under its plugin, with
its own checkbox, its URL, and a secret picker for each header
variable. This works for default plugins too, whose plugin checkbox
stays locked. The code does not detect duplicate servers. To remove a
duplicate, a person unchecks one of the two. When a server's origin
changes, the UI shows the new URL and asks for the secrets again.

### Secret purpose

A new runner-only purpose, `mcp_header`, delivers a header secret. Like
the other setup purposes, a grant for `mcp_header` can use only the
`file_descriptor` delivery mode, so a model command can never receive
it. A `run_with_secret` grant uses the `environment` delivery mode, so
the two purposes are always in separate grants. A binding can have
both grants, and then the model can also use the token in a command.

When a person picks a secret for a header variable, the Tools and
plugins section adds `mcp_header` to the agent's `file_descriptor`
grant for that binding, or creates that grant. A grant applies at once
and is not part of the agent version. `mcp_server` stays retired.

### Runner relay

The runner removes each relayed server and each turned-off server from
its copy of the plugin. Root owns that copy, so the model cannot add a
server back. For each relayed server, the runner resolves the secrets
with the purpose `mcp_header` and opens an MCP client session through
its egress proxy. It fills the headers on each request, so a refreshed
credential applies to the open session.

The relay sends a credential only to the origin in the agent's entry,
and only over `https`. If the server URL no longer has that origin, the
runner does not relay the server and adds a task warning. The relay
follows a redirect only to the same origin.

The runner gives the CLI each relayed server as an in-process SDK
server named `plugin:<plugin>:<server>`. The CLI names its tools
`mcp__plugin_<plugin>_<server>__<tool>`, the names that the tools of
the plugin's own server would have. So allow rules, the tool policy,
and the server statuses treat relayed tools as the plugin's tools.
Every call goes through the `PreToolUse` hook. The model's `Bash`
cannot reach the relay, because the CLI talks to the relay over the SDK
control channel and not over a socket.

The relay forwards tools only, with the safeguards of the Imbi relay,
the relay for Imbi's own MCP server. Each call has a timeout, a limit
on result size, and ends when the task stops. The relay removes each
secret value from a result, in case the server echoes a request header.

The relay does not forward resources or prompts. The model cannot read
MCP resources today: `ListMcpResourcesTool` and `ReadMcpResourceTool`
are not built-in tools that an agent can turn on, and the tool policy
denies a built-in tool that is not on the list. An MCP prompt runs only
when a person types it, and no person types in an agent task. The relay
can forward resources later, together with those two tools.

Each result goes to the model in `<untrusted>` tags. The harness puts
text from outside Imbi in these tags, and the task prompt tells the
model that their content is data and not instructions. A relayed
result comes from a third-party server, and the relay has it in hand,
so the relay wraps it, as the Imbi relay wraps its results. The CLI
passes the results of a server that it connects to itself straight to
the model, and the harness does not change them.

The relay keeps one session per server for the life of the task. If
the server drops the session, the relay opens a new one but does not
repeat the failed call, because the state the server kept in the old
session is gone. The call returns an error instead.

The SDK bridge to an in-process server drops server notifications,
such as `tools/list_changed`, and refuses requests that a server sends
to its client, such as sampling and elicitation.

### Server problems show as task warnings

A plugin server's problem shows as a task warning in the Conversation
tab. The task gets one when a server's status is `failed`,
`needs-auth`, or still `pending` after a short wait, when the relay
cannot open or keep a session, when a header variable has no secret
and no default, and when the agent's entries do not match the pinned
plugin. No warning fails the task.

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
- The relay depends on the CLI naming the tools of an in-process
  server `plugin:<plugin>:<server>` as
  `mcp__plugin_<plugin>_<server>__<tool>`. Allow rules and the tool
  policy depend on it too. If a CLI upgrade changed the names, they
  would stop matching relayed tools, so an isolation test must guard
  this naming.
- An agent can turn off any server of a plugin, including a default
  plugin, and keep the plugin's skills, hooks, and commands.
- A person can see every server of a plugin before enabling it.
- Results of relayed servers reach the model in `<untrusted>` tags.
  Results of a plugin server that the CLI connects to itself do not.
- A revoked grant does not stop a running task that uses a static
  secret. A credential with an expiry works until its next refresh,
  which is denied.
- A server that keeps state in a session, such as a selected
  workspace, loses it when the session drops. The model must set that
  state up again.
- The CLI does not know a relayed server's URL, so two relayed servers
  with the same URL both load. Only the checkboxes prevent this.
- A server that needs `headersHelper`, OAuth, or a URL variable still
  does not work in an agent. Its status now shows in the task.

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
a server that keeps state in a session would lose it after every call.
The relay already applies a refreshed credential to the open session.

### Resolve the secrets again on a fixed interval

Not chosen. Each resolution is a broker call and an audit event. The
only gain is that a revoked grant stops a running task sooner. The
clone and marketplace tokens do not do this either.

### Detect duplicate servers in code

Refused. Two plugins can declare one URL with different headers. The
checkboxes let a person keep the one they want.
