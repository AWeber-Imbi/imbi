# Agents

The **Agents** area defines the agents of an organization. An agent is a
named configuration: an owner team, a system prompt and a model, the tools
and plugins it can use, the secrets it can request, and its limits. Agents
do work in [agent tasks](agent-tasks.md). Runner pods run the tasks (see
[Agent Runners](../deployment/agent-runners.md)).

The **Agents** menu in the top bar shows when you have `agent:read`. Each
organization has its own agents. Select the organization in the top bar
first.

The area has these pages:

| Page | Menu path | What it shows |
|---|---|---|
| Dashboard | **Agents > Dashboard** | Agent activity at a glance |
| Tasks | **Agents > Tasks** | The task inbox. See [Agent tasks](agent-tasks.md) |
| Usage | **Agents > Usage** | Tokens and spend |
| Agents | **Agents > Settings > Agents** | The agent list, the agent detail, and the editor |
| Workflows | **Agents > Settings > Workflows** | See [Workflows](workflows.md) |
| Platform | **Agents > Settings > Platform** | The base configuration and the plugin marketplaces |

## Permissions

| Permission | Lets you | Roles that have it |
|---|---|---|
| `agent:read` | See agents, their versions, and the tool catalog | `admin`, `developer`, `default`, `readonly` |
| `agent:create` | Create and duplicate agents | `admin`, `developer` |
| `agent:write` | Edit, enable, disable, and restore agents. Refresh the tool catalog | `admin`, `developer` |
| `agent:delete` | Delete agents | `admin` |
| `agent_platform_config:write` | Change the base configuration and the marketplaces | `admin` |
| `prompt:create`, `prompt:update` | Save a change to the system prompt or the model | `admin`, `developer` |
| `secret_grant:read`, `secret_binding:read`, `secret_grant:write` | See and add grants on the **Access** tab | `admin` |

You must also be a member of the organization. For the task permissions,
see [Agent tasks](agent-tasks.md#permissions). For roles, see
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
| Description | One sentence. The task inbox and the workflow picker show it |
| Icon | An icon, or an image that you upload (500 KB maximum) |
| Slack channel | A channel name, for example `#cs-escalations`. Imbi stores it. In this release, nothing uses it |
| Owner team | Required. The team that owns the agent |
| Labels | Organization tags. You can make a label with a color from this field |

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
| `{{ project }}` | The project slug of the task, or empty |

The **System prompt** tab is a Markdown editor. The **Model** tab has these
fields:

| Field | What it does |
|---|---|
| LLM provider | Filters the model list by provider |
| Model | An enabled generative model from [AI Models](ai-models.md). The list shows the context window and the price |
| Max tokens, Extended thinking, Prompt caching, Temperature, Top K, Top P | Click **Show advanced controls**. A parameter that is off is not set, and the provider default applies |

### Tools and plugins

This tab sets what the agent can call. It has two parts.

**Plugins** lists the plugins of the marketplaces that the organization
allows (see [Plugin marketplaces](#plugin-marketplaces)). Select a plugin
to give it to the agent. Each row names the MCP servers that the plugin
brings. While a plugin is on, the agent can use every tool of its MCP
servers.

- When you save, Imbi pins each new plugin to the commit that it synced
  last.
- When a newer commit exists, the row shows **Pin** with the commit. Click
  it, then save, to use the newer commit.
- A default plugin of the organization is selected and you cannot clear it.
- A plugin with the badge **unsupported source** cannot load. See
  [Plugin sources](#plugin-sources).

**Tools** lists the tools in groups:

- The `imbi` group has the tools of the Imbi API.
- Each other group is an MCP server from **Admin > Global Admin >
  Assistant > MCP Servers**. The assistant and the Slack bot use the same
  servers.

The key of a tool is `<server slug>.<tool name>`. Each tool has a
capability badge: **Read**, **Write**, **Destructive**, or **Unknown**. The
badge comes from the MCP annotations of the tool.

To give the agent a tool:

1. Find the tool. Use the search field, the **Capability** filter, or
   **Enabled only**.
2. Turn on the switch of the tool. **Enable all** turns on all the tools of
   a server.
3. Optional: click **Approval**. Then a person must approve each call. See
   [Approvals](agent-tasks.md#answer-a-request).
4. Optional: click an environment chip to block that environment. A
   blocked environment is not highlighted. The runner refuses a call whose
   `environment` argument names a blocked environment.
5. Optional: click the rate limit button. Enter the number of calls and
   select **Per minute**, **Per hour**, or **Per day**. Click **Apply**.

Imbi keeps the tool list for 5 minutes. Click the refresh button to list
the tools again. The refresh connects to each MCP server, so it needs
`agent:write`.

When a server does not answer, its group shows an error: not reachable, no
answer in time, or credentials not accepted. A tool that the agent has but
that the catalog does not list now shows **Unavailable**. Turn it off to
remove it.

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
| `github_write` | Push, and open pull requests and issues | `environment` |
| `marketplace_fetch` | Fetch plugins from private marketplaces | `file_descriptor` |

A missing purpose shows a **Grant** button. Click it to make a grant for
this agent, this binding, and that purpose. For the App setup, see
[Configure GitHub access](../deployment/agent-runners.md#6-configure-github-access).

**Secrets** lists the secrets that the agent can request with
`run_with_secret`. Each secret goes into the environment of one command. To
add one:

1. Click **Add access**.
2. Select the **Secret**.
3. Enter the **Purpose**, for example `npm`.
4. Click **Save**.

The tab also lists the secrets that the runner uses for the agent, for
example the model key and MCP server credentials. The agent never gets
these values. To change or remove a grant, use **Admin > \<organization\>
Admin > Secrets**.

### Subagents

An agent can give work to other agents. Each such call makes a child task
(see [Related tasks](agent-tasks.md#relations-and-associated-projects)).

1. Select each agent that this agent can delegate to. The list shows the
   enabled agents of the organization.
2. Optional: click **Add instructions** and enter the delegation
   instructions for that subagent.

An agent cannot name itself. Cycles are allowed. A link uses the id of the
subagent, so a rename does not break it.

### Settings

An empty field means no limit.

| Field | What it does |
|---|---|
| Monthly cost cap | USD. Advisory only: warnings show at 80% and 100%. The agent still runs. See [Usage](#usage) |
| Task budget | USD. The default hard budget of each task. A task can only lower it. See [Budgets](agent-tasks.md#budgets) |
| Max concurrent tasks | The number of tasks of this agent that can run at the same time |
| Task timeout | For example `30m` or `2h`. A number with no unit is minutes. A task that runs longer closes with `exceeded_ceiling` |
| Required runner labels | Labels, separated by commas. Only a runner with every label runs the tasks of this agent. See [Labels and exclusive pools](../deployment/agent-runners.md#labels-and-exclusive-pools) |
| Human response SLA | 4 hours, 8 business hours, 24 hours, 3 days, or No SLA. Imbi stores it. In this release, nothing uses it |

### Narrowing fields

The agent settings also have `permission_mode`, `sandbox`, `denied_tools`,
and `approval_tools`. They narrow the organization's
[base configuration](#base-configuration). The editor has no controls for
them. Set them with the API.

## Enable and disable an agent

On the agent list, use the switch on the row. A disabled agent:

- Gets no new tasks. A create returns `409`.
- Has no **Run** button.
- Is not in the **New task** dialog.
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
removes the agent, its versions, and its service account. The prompt stays
in the prompt CMS.

The delete returns `409` when:

- Another agent delegates to this agent. The tab lists those agents.
  Remove this agent from each of them first.
- A workflow uses this agent. Remove it from each workflow first.

## Agent detail

Open an agent from the list. The detail page shows:

- The owner team, model, Slack channel, settings, and labels.
- **Runs (30 days)** and the monthly cost cap, with a badge at 80% and
  100%.
- **Cost over time**: daily cost and runs for the last 30 days.
- **Tools and MCP access**, **Subagents**, and the **System prompt**.
- **Run**, **Duplicate**, and **Edit**. **Run** opens the
  [New task](agent-tasks.md#create-a-task) dialog with this agent.

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
| Allowed tools | Built-in tools, separated by commas. Empty allows all |
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
reads through the organization's GitHub integration. A failed sync shows an
error badge on the row. Click the sync button of a row to sync it again.
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

With a GitHub App binding, put each marketplace and plugin repository in
the `repositories` of the binding. Otherwise the task fails with
`marketplace_fetch_failed`.

## Usage

Open **Agents > Usage**. Select a range (the last 7, 30, or 90 days) and
an agent. The page shows:

- Tiles with the totals: tokens in, tokens out, and spend.
- A daily chart by agent. Use **Cost** or **Token usage**.
- **Usage by agent**: tasks, tokens in, tokens out, cache hit, and cost,
  with a total row.

Imbi calculates the cost from the token counts and the prices in
[AI Models](ai-models.md). A usage report for a model with no price counts
as $0. The page tells you how many reports had no price.

- **Tasks** counts the tasks made in the range. The cost in the range can
  include tasks made before it.
- The monthly cost cap uses the UTC calendar month. At 80% and 100% of a
  cap, the page shows a banner. The cap does not stop the agent.

The page needs `agent_task:read`. The API is
`GET /organizations/{org}/agent-usage/`, with `start`, `end`, and
`agent_id`.

## Dashboard

Open **Agents > Dashboard**. It needs `agent_task:read`.

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
