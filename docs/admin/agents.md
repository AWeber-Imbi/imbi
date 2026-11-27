# Agents

The **Agents** area defines the agents of an organization. An agent is a
named configuration: an owner team, a system prompt and a model, the tools
and plugins it can use, the secrets it can request, and its limits. Agents
do work in [tickets](tickets.md). Runner pods run the tasks (see
[Agent Runners](../deployment/agent-runners.md)).

The **Agents** menu in the top bar shows when you have `agent:read`. Each
organization has its own agents. Select the organization in the top bar
first.

The area has these pages:

| Page | Menu path | What it shows |
|---|---|---|
| Dashboard | **Agents > Dashboard** | Agent activity at a glance |
| Tickets | **Tickets** (top bar) | The ticket list. It is a top-level page, not in the Agents area. See [Tickets](tickets.md) |
| Agents | **Agents > Settings > Agents** | The agent list, the agent detail, and the editor |
| AI Models | **Agents > Settings > AI Models** | See [AI Models](ai-models.md). Platform administrators only |
| Platform | **Agents > Settings > Platform** | The base configuration and the plugin marketplaces |
| Secrets | **Agents > Settings > Secrets** | See [Secrets](secrets.md). Platform administrators only |
| Workflows | **Agents > Settings > Workflows** | See [Workflows](workflows.md) |

## Permissions

| Permission | Lets you | Roles that have it |
|---|---|---|
| `agent:read` | See agents, their versions, and the tool catalog | `admin`, `developer`, `default`, `readonly` |
| `agent:create` | Create and duplicate agents | `admin`, `developer` |
| `agent:write` | Edit, enable, disable, and restore agents. Refresh the tool catalog | `admin`, `developer` |
| `agent:delete` | Delete any agent. With `agent:write` only, you can delete an agent of a team that you are in | `admin` |
| `agent_platform_config:write` | Change the base configuration and the marketplaces | `admin` |
| `prompt:create`, `prompt:update` | Save a change to the system prompt or the model | `admin`, `developer` |
| `secret_grant:read`, `secret_binding:read`, `secret_grant:write` | See grants on the **Access** tab. Add and remove grants on the **Access** tab. Without `secret_binding:write`, add and remove only for an agent of a team that you are in, and only for a **Grantable** binding | `admin`, `developer` |
| `secret_provider:read` | Choose a GitHub App on the **Access** tab | `admin`, `developer` |

You must also be a member of the organization. The permissions come from
your role in that organization only. For the task permissions,
see [Tickets](tickets.md#permissions). For roles, see
[Roles and permissions](roles-and-permissions.md).

## Create an agent

1. Open **Agents > Settings > Agents**.
2. Click **New Agent**.
3. Complete the tabs. The sections below describe each tab.
4. Click **Create Agent**.

A new agent is enabled. Imbi also makes a service account for the agent.
The agent acts as this service account when it calls Imbi. Imbi deletes the
service account when you delete the agent.

To copy an agent, open it and click **Duplicate**.

### Overview

| Field | What to enter |
|---|---|
| Agent name | Required. Imbi makes the slug from the name |
| Icon | An icon, or an image that you upload (500 KB maximum) |
| Slack channel | A channel name, for example `#cs-escalations`. Imbi stores it. In this release, nothing uses it |
| Owner team | Required. The team that owns the agent |
| Tags | Organization tags. They only classify the agent and have no effect on runner selection. You can make a tag with a color from this field |

You do not write the description. When a save changes the name, the
system prompt, the tools, or the subagents, a model writes one sentence
that says what the agent does and names its subagents. The task inbox,
the agent list, and the workflow picker show it. The prompt is
`imbi-api/agent-description` in the [prompt CMS](prompts.md). Edit it,
and choose its model, on **Agents > Platform**. Without a model,
imbi-api uses its default Anthropic model. When no model answers, or the
agent has no system prompt, tools, or subagents, the save keeps the
description that the agent had. An agent with an empty description gets
one on its next save, if a model answers and the agent has a system
prompt, tools, or subagents.

### System prompt and model

The system prompt, the model, and the model parameters are not stored on
the agent. They are a prompt in the [prompt CMS](prompts.md), with the
reference `agents/<organization slug>.<agent slug>@stable`.

When you save a change to the **System prompt** tab or the **Model** tab,
Imbi does these steps:

1. It writes a new version of the prompt. For a new agent, it creates the
   prompt.
2. It moves the `stable` label to the new version.
3. It saves the agent, with the number of the prompt version.

Step 2 needs `agent:write` or `prompt:promote`. `agent:write` is enough
because the prompt belongs to the agent. On any other prompt, a label
move needs `prompt:promote`.

The system prompt can use these variables. Imbi fills them in when a
runner starts a task. Each prompt version that the editor saves declares
them.

| Variable | Value |
|---|---|
| `{{ organization }}` | The organization slug |
| `{{ agent }}` | The agent slug |
| `{{ task }}` | The task id, for example `T-42` |
| `{{ project_slug }}` | The project slug of the task, or empty |

The **System prompt** tab is a Markdown editor. The **Model** tab has these
fields:

| Field | What it does |
|---|---|
| LLM provider | Filters the model list by provider. Changing it clears the model |
| Model | An enabled generative model from [AI Models](ai-models.md). The list shows the context window and the price |
| Effort | Claude models only: `Low`, `Medium`, `High`, `Extra high`, or `Max`. Higher effort makes the model think more and use more tokens. A Claude model starts at `Medium`, and an agent with a Claude model always saves an effort level |
| Max tokens, Prompt caching | Click **Show advanced controls**. A parameter that is off is not set, and the provider default applies |

Agents expect Claude 5 models or later. A Claude 4 model can reject some
effort levels.

### Tools and plugins

This tab sets what the agent can call. It has two parts.

**Plugins** lists the plugins of the marketplaces that the organization
allows (see [Plugin marketplaces](#plugin-marketplaces)). Select a plugin
to give it to the agent. Under each plugin, the row lists the MCP servers
that the plugin brings, with the URL of each server, or `stdio` for a
server that runs as a local command. While a plugin is on, the agent can
use every tool of its MCP servers that is checked.

- When you save, Imbi pins each new plugin to the commit that it synced
  last, and saves the list of its MCP servers at that commit.
- When a newer commit exists, the row shows **Pin** with the commit. Click
  it, then save, to use the newer commit.
- A default plugin of the organization is selected and you cannot clear it.
  It uses the commit that the organization pins, so its row shows no
  **Pin**.
- A plugin with the badge **unsupported source** cannot load. See
  [Plugin sources](#plugin-sources).

Clear the checkbox of an MCP server to turn it off for the agent. The agent
keeps the plugin's skills, commands, and other servers. This works for a
default plugin too. When two plugins bring servers with the same URL, turn
off the one you do not want. The list shows the servers of the commit that
the agent runs. For a plugin pinned before Imbi saved this list, it shows
the servers of the newest synced commit and, when the agent runs an older
commit, the note "Servers at <commit>. This agent runs <commit>."

An `http` or `sse` server whose headers use `${VAR}` variables shows a
secret picker for each variable. Pick a secret to have the runner fill
that header. The list offers each enabled binding that allows
`file_descriptor` delivery and is not a provider key or a GitHub App
binding. For a binding with a field list, pick a field.

- Picking a secret records the origin of the server URL that the row
  shows, and the runner sends the secret only to that origin, over
  `https`. A server URL that is not `https` shows no pickers.
- Picking a secret also grants it to the agent at once, with the
  purpose `mcp_header`: Imbi adds the purpose to the agent's own
  `file_descriptor` grant of that binding, or creates that grant. The
  grant applies at once and is not part of the agent version. The
  picker shows whether a grant allows it, and **Grant** when it does
  not. For a new agent, save first, then click **Grant**.
- A grant for some projects only does not count, because a task for
  another project would get no secret.
- Picking a secret needs `secret_binding:read`, `secret_grant:read`,
  and `secret_provider:read`. Without them, you can only choose **No
  secret**.
- A plugin pinned before Imbi saved its server list shows no pickers.
  Click **Pin**, then save, to pin it again. For a default plugin, the
  organization must pin it again.
- Choose **No secret** to unmap a variable. A server that is on and has
  no secrets needs no setting, so the save drops it.
- Turning a server off keeps its secrets for when you turn it on again.

When a new pin moves a server to another origin, the row shows the new
URL and asks you to pick its secrets again. Until you do, the agent does
not get the server. **Remove the secrets** drops them instead.

When the agent moves to a commit that no longer has a server that you
turned off or gave secrets, the save drops the setting, and it drops the
secret of a header variable that the server no longer uses. Otherwise the
server is listed under its plugin as **no longer in this plugin**. Click
**Remove**, then save, to drop the setting. If the server was renamed,
set up its new name again.

While a task runs, the Conversation tab shows a warning, and the task goes
on, when:

- An MCP server of a plugin is `failed` or `needs-auth`, or is still
  `pending` or did not load 60 seconds after the agent session starts. A
  task that ends sooner gets no warning for a pending server.
- A header of a server uses a `${VAR}` that has no default, no picked
  secret, and no value in the Claude Code environment. The header is sent
  empty.
- The runner cannot relay a server with secrets: its URL is no longer an
  `https` URL at the origin that you picked the secrets for, or the
  secrets broker refuses a secret. The agent does not get that server.
- The agent turns off a server that the pinned plugin does not have.

**Tools** lists two groups: **Built-in** and **Imbi**. The MCP
servers in **Admin > &lt;Org&gt; Admin > MCP Servers** are for the
assistant only and are not in this list. To give the agent other MCP
servers, select a plugin that brings them.

**Imbi** has the tools of the Imbi API. The key of a tool is
`imbi.<tool name>`. Each tool has a capability badge: **Read**,
**Write**, **Destructive**, or **Unknown**. The badge comes from the MCP
annotations of the tool.

**Built-in** has the Claude Code built-in tools that are off for every
agent until you turn them on for one agent:

| Key | Tool | What it does |
|---|---|---|
| `builtin.Skill` | `Skill` | Loads a skill from the plugins of the agent |
| `builtin.Agent` | `Agent` | Starts a Claude Code subagent for part of the task |

The other built-in tools (`Bash`, `Read`, `Edit`, ...) come from the
**Allowed tools** of the [base configuration](#base-configuration), not
from this tab. Without its switch, the runner refuses a call of `Skill`
or `Agent` with `tool_not_allowed`. The base configuration still applies:

- When **Allowed tools** is empty, you can turn on each opt-in tool here.
- When **Allowed tools** has a list, it is the ceiling. Add `Skill` or
  `Agent` to it, then turn the tool on for each agent that needs it. A
  tool in the list stays off for an agent that does not turn it on.
- A tool in **Denied tools**, of the organization or the agent, stays
  off. `Task`, the earlier name of `Agent`, denies `Agent` too.

A subagent and the tools that a skill uses are checked like every other
tool call of the agent. A subagent runs in the foreground: the agent
waits for its result before it goes on, and the task does not close
while a subagent runs.

To give the agent a tool:

1. Find the tool. Use the search field, the **Capability** filter, or
   **Enabled only**.
2. Turn on the switch of the tool. **Enable all** turns on all the tools.
3. Optional: click **Approval**. Then a person must approve each call. See
   [Approvals](tickets.md#answer-a-request).
4. Optional: click an environment chip to block that environment. A
   blocked environment is not highlighted. The runner refuses a call whose
   `environment` argument names a blocked environment. A built-in tool has
   no environment chips.
5. Optional: click the rate limit button. Enter the number of calls and
   select **Per minute**, **Per hour**, or **Per day**. Click **Apply**.

Imbi keeps the tool list for 5 minutes. Click the refresh button to list
the tools again. The refresh needs `agent:write`.

When Imbi cannot list the tools, the list shows an error. A tool that the
agent has but that the catalog does not list now, for example a `zoekt.*`
tool from before 2.45.0, shows **Unavailable** under **Not in the catalog**.
Turn it off to remove it.

### Access

This tab shows what the agent can get from the
[secrets broker](secrets.md). Grants apply at once. They are not part of
the agent version. A new agent gets grants only after its first save.

**GitHub App**: select the `github_app` binding of the agent's own GitHub
App. The binding is saved with the agent. The tab then shows one row for
each purpose:

| Purpose | Used for | Delivery |
|---|---|---|
| `workspace_checkout` | Clone the project repositories | `file_descriptor` |
| `github_read` | Read pull requests, issues, and CI run logs | `environment` |
| `github_write` | Push, and open pull requests and issues | `environment` |
| `github_status` | Publish check runs and commit statuses | `environment` |
| `marketplace_fetch` | Fetch plugins from private marketplaces | `file_descriptor` |

A missing purpose shows a **Grant** button. Click it to make a grant for
this agent, this binding, and that purpose. For the App setup, see the
[GitHub App Runbook](github-app-runbook.md).

A running agent can add a project of the organization to its own task with
the `attach_project` tool, by id or slug. The task gets a
`project.associated` event, and the next secret that the agent requests
covers the project's repository. The `detach_project` tool removes one
again (`project.dissociated`), so the next secret no longer covers it. A
task keeps at least one project (`last_project`): a grant that lists
projects never matches a task with none. A GitHub token covers the
repositories of every project on the task, and those must be in one
GitHub organization, so an agent that moves to a repository of another
organization attaches its project, then detaches the old one before it
requests the next secret.

**Secrets** lists the secrets that the agent can request with
`run_with_secret`. Each secret goes into the environment of one command.
The agent sees the description and the allowed fields of each binding, so
write a description that tells the agent what the secret is for. To add
one:

1. Click **Add access**.
2. Select the **Secret**.
3. Enter the **Purpose**, for example `npm`.
4. Click **Save**.

The tab also lists the secrets that the runner uses for the agent, for
example the model key, the repository tokens, and the MCP server header
secrets. The agent never gets these values.

To remove a secret, click **X** on its row. This removes the agent from
the grant. A grant that names other agents stays for them. A grant that
names no other agent is deleted. A grant can cover more than one secret;
the agent then loses all of them. To change a grant, use **Agents >
Settings > Secrets**.

Without `secret_binding:write`, you can add and remove access only for
an agent of a team that you are in. **Add access** and the **Grant**
buttons offer only the bindings that an administrator marked
**Grantable** (see [Add a binding](secrets.md#add-a-binding)).

### Subagents

An agent can give work to other agents. Each such call makes a child task
(see [Related tasks](tickets.md#relations-and-associated-projects)).

1. Select each agent that this agent can delegate to. The list shows the
   enabled agents of the organization, this agent included.
2. Optional: click **Add instructions** and enter the delegation
   instructions for that subagent.

An agent can name itself, for example to give each repository of a ticket
its own child task. Cycles are allowed. Delegation depth is capped at 2: a
child task gets no subagents, and the harness refuses a child of a child
with `delegation_depth`. A link uses the id of the subagent, so a rename
does not break it.

### Settings

An empty field means no limit.

| Field | What it does |
|---|---|
| Monthly cost cap | USD. Advisory only: warnings show at 80% and 100%. The agent still runs. See [Usage](#usage) |
| Task budget | USD. The default hard budget of each task. A task can only lower it. See [Budgets](tickets.md#budgets) |
| Max concurrent tasks | The number of tasks of this agent that can run at the same time |
| Task timeout | For example `30m` or `2h`. A number with no unit is minutes. A task that runs longer closes with `exceeded_ceiling` |
| Required runner labels | Used only to select a harness runner. Labels, separated by commas. Only a runner with every label runs the tasks of this agent. See [Labels and exclusive pools](../deployment/agent-runners.md#labels-and-exclusive-pools) |
| Egress destinations | The internal hosts that the pod of the agent's chains may reach, in addition to the global ones. See [Egress allowlists](../deployment/agent-runners.md#egress-allowlists). A host name destination works only for HTTPS clients that use the egress proxy, and the DNS owner of each name controls where it goes: see [Host name destinations](../deployment/agent-runners.md#host-name-destinations) |
| Human response SLA | A duration such as `4h`, `1d`, `2w` or `1h30m` (units `s`, `m`, `h`, `d`, `w`). Empty is no SLA. When a request of the agent is still open after it, the slackbot posts the request to a team Slack channel. See [Slack](../slackbot/index.md#answer-a-ticket-that-needs-input) |

### Narrowing fields

The agent settings also have `permission_mode`, `sandbox`, `denied_tools`,
and `approval_tools`. They narrow the organization's
[base configuration](#base-configuration). The editor has no controls for
them. Set them with the API.

## Enable and disable an agent

On the agent list, use the switch on the row. A disabled agent:

- Gets no new tasks. A create returns `409`.
- Has no **Run** button.
- Is not in the **New ticket** dialog.
- Does not run its queued tasks.

A change to only the enabled state writes no version.

## Versions

Each save that changes the agent writes a new version. A save that changes
nothing writes no version. Each version records the prompt version, so a
restore also brings back the system prompt and the model.

To restore a version:

1. Open the agent, click **Edit**, then open the **Version history** tab.
2. Click **Restore** on the version.
3. Read the dialog. It names the label move, for example
   `agents/acme.triage@stable → v3`.
4. Confirm.

The restore writes a new version with the summary `Restored v<n>`. It
needs `agent:write`. That is also enough to move the prompt label.

- A restore moves a label only on the agent's own
  `agents/<organization slug>.` prompt. For any other prompt, it returns
  `409`.
- An agent made before the organization-scoped prompt slugs returns `409`.
  Change and save its system prompt one time, then restore.
- A subagent that no longer exists is removed. The version summary says
  so.

## Delete an agent

Open the **Version history** tab and click **Delete agent**. The delete
removes the agent, its versions, and its service account, and removes the
agent from its secret grants. The prompt stays in the prompt CMS.

You need `agent:delete`, or `agent:write` and membership of the agent's
owner team. Without either, the API returns `403`.

The owner team can delete the agent and grant it secrets, so changing
the **Team** of an agent also needs `agent:delete` or membership of the
current owner team (`403 owner_team_forbidden`).

The delete returns `409` when:

- Another agent delegates to this agent. The tab lists those agents.
  Remove this agent from each of them first.
- A workflow uses this agent. Remove it from each workflow first.

## Agent detail

Open an agent from the list. The detail page shows:

- The owner team, model, Slack channel, settings, and tags.
- **Runs (30 days)** and the monthly cost cap, with a badge at 80% and
  100%.
- **Cost over time**: daily cost and runs for the last 30 days.
- **Tools and MCP access**, **Subagents**, and the **System prompt**.
- **Run**, **Duplicate**, and **Edit**. **Run** opens the
  [New ticket](tickets.md#create-a-ticket) dialog with this agent.

The agent list also shows **Runs 30d**, **Cost 30d**, and **Avg / run**.

## Base configuration

Open **Agents > Settings > Platform**. Each organization has one base
configuration. Each save writes a new version. Every task pins the version
that was current when the task was made.

An agent can only narrow the base configuration. An agent save that widens
a setting returns `422`. When Imbi merges the two, it always uses the
stricter value.

| Field | What it does |
|---|---|
| Model upstream | **Anthropic API** or **LiteLLM gateway** |
| Base URL | The upstream URL. Empty is the Anthropic API |
| Key | The `secret://` reference of the model key. See [Configure the model key](../deployment/agent-runners.md#5-configure-the-model-key) |
| Permission mode | `plan`, `default`, `acceptEdits`, or `bypassPermissions`, strictest first. Agents can set a stricter mode only |
| Sandbox | **Require the sandbox** and **Allow unsandboxed commands** |
| Allowed tools | Built-in tools, separated by commas. Empty allows all. `Skill` and `Agent` are on only for an agent that turns them on in its **Tools** tab |
| Denied tools | Agents can deny more |
| Approval tools | Tools that need approval when an automation starts the task (not a person) |
| System prompt prefix | Put before the system prompt of each agent |
| Hooks | Agent SDK hooks, as JSON. Agents cannot change them |
| Allowed marketplaces and default plugins | The marketplaces that agents can use, and the plugins that every agent gets |

Click **Save version**. Without `agent_platform_config:write`, the page is
read only.

## Plugin marketplaces

A marketplace is a git repository with a `.claude-plugin/marketplace.json`
file, in the Claude Code marketplace format.

To add a marketplace:

1. Open **Agents > Settings > Platform**.
2. In **Plugin marketplaces**, enter a **Slug** and the **Git URL**, for
   example `https://github.com/anthropics/claude-code`.
3. Click **Add marketplace**. Imbi syncs it at once.
4. In **Base configuration**, select the marketplace in **Allowed
   marketplaces and default plugins**.
5. Click **Save version**.

A sync reads the marketplace file at the head of the default branch. It
reads through the organization's GitHub integration. When no integration can
read a `github.com` repository, the sync reads it anonymously. It reads
files from `raw.githubusercontent.com`, and commits from the GitHub API.
GitHub limits anonymous API requests to 60 an hour for each API pod IP
address. A repository on another host is never read anonymously.

The sync also reads the MCP servers of each plugin, with the rule that
runners use to load the plugin. When the plugin directory has a
`.claude-plugin/plugin.json`, the servers come from its `mcpServers`.
Otherwise they come from the `mcpServers` of the plugin's entry in
`marketplace.json`. For a `url` or `github` source, that entry is the one
in the `marketplace.json` of the plugin's own repository. The servers of
the plugin's `.mcp.json` are added in both cases. As in the CLI, the
sync reads `.mcp.json` first, and of two definitions of one server name,
the later one is kept. A missing or invalid file adds no servers. A file
counts as missing when no reader can read it and at least one reader
finds no such file, even if another reader
fails, so such a sync can replace the catalog without an error badge.
GitHub answers a private repository that a reader cannot access with the
same "not found". When every reader fails, the sync fails and the
previous catalog stays. A server file path that is absolute or contains
`..` adds no servers, and the API logs a warning, because the runner
fails each task of a plugin with such a path. For each server, Imbi
stores its name, type, URL, and the names of its headers with the
variables that each header uses. It stores no header value, no user
information, query, or fragment of a URL, and no URL that has no host,
such as one that starts with a `${VAR:-default}` reference. It keeps the
path of a URL, so a token in the path is stored. A failed
sync shows an error badge on the row. Click the sync button of a row to
sync it again.
Imbi does not sync on a schedule.

You cannot delete a marketplace that the newest base configuration allows.
Pinned plugins keep their URL and commit, so the tasks of existing agent
versions still run them.

### Plugin sources

| Source in `marketplace.json` | Supported |
|---|---|
| A relative path in the marketplace repository | Yes |
| An inline entry, with no `.claude-plugin/plugin.json` in the plugin directory | Yes. The runner uses the entry from `marketplace.json` |
| `url` (https only) | Yes, when the sync resolves a commit |
| `github` (`owner/name`) | Yes, when the sync resolves a commit |
| `npm`, `pip`, `git-subdir`, and others | No |

For a `url` or `github` source, the sync uses the `sha` of the source, else
its `ref`, else the head of the default branch.

An external plugin must be on the same host as the marketplace. The runner
uses its `marketplace_fetch` token for the plugin, and that token is for
the marketplace host. A `github` source is on `github.com`. A plugin on
another host shows **unsupported source**.

With a GitHub App binding, an empty `repositories` list allows each
marketplace and plugin repository of the App installation. Otherwise, only
the listed repositories are allowed. The runner names one repository for
each token, so each token covers one repository. When
the token is refused or the clone fails, the runner clones a `github.com`
repository anonymously. This works only for a public repository. Otherwise, and for a
repository on another host, the task fails with `marketplace_fetch_failed`.

## Usage

Open **Reports > Agent Usage**. Select a range (the last 7, 30, or 90 days) and
an agent. The page shows:

- Tiles with the totals: tokens in, tokens out, and spend.
- A daily chart by agent. Use **Cost** or **Token usage**.
- **Usage by agent**: tasks, tokens in, tokens out, cache hit, and cost,
  with a total row. Usage of a deleted agent shows as **Deleted** and the
  agent ID.

Imbi calculates the cost from the token counts and the prices in
[AI Models](ai-models.md). A usage report for a model with no price counts
as $0. The page tells you how many reports had no price.

- **Tickets** counts the tickets made in the range. The cost in the range can
  include tickets made before it.
- The days, the range, and the monthly cost cap use the calendar in the
  time zone of your browser. At 80% and 100% of a cap, the page shows a
  banner. The cap does not stop the agent.

The page needs `ticket:read`. The API is
`GET /organizations/{org}/agent-usage/`, with `start`, `end`, `agent_id`,
and `tz` (an IANA time zone; the default is UTC).

## Dashboard

Open **Agents > Dashboard**. It needs `ticket:read`.

| Section | What it shows |
|---|---|
| Tiles | **Running**, **Waiting on people** (with the oldest wait), **Queued**, **Runs** (30 days), and **Spend this month** |
| Needs attention | Tasks that wait on a person, oldest first. Then tasks closed in the last 7 days with the outcome `failed_external`, `failed_at_gate`, `exceeded_ceiling`, `partial_capped`, or `request_expired`. Then agents at 80% or more of their monthly cost cap |
| Busiest agents | The top 5 agents by runs in the last 30 days |
| Waiting on people | Waiting tasks by owner, with the count, the oldest wait, and the median wait |
| Recent runs | The 8 newest tasks |

The dashboard reads at most 100 open tasks and 50 recent tasks.

See [ADR 0020](../api/adr/0020-agent-task-contract.md) and
[ADR 0022](../api/adr/0022-agent-harness-and-secrets-broker.md) for the
design.
