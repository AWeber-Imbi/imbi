# ADR 0029: Automations

Date: 2026-11-16

## Status

Accepted

Related: [ADR 0020](0020-agent-task-contract.md) (agent tasks; a project
run is an agent task), [ADR 0021](0021-workflow-contract.md) (workflows;
one new step), [ADR 0022](0022-agent-harness-and-secrets-broker.md)
(harness and secrets broker; a second engine and new token purposes),
[ADR 0028](0028-tasks-become-tickets.md) (accepted; read "agent task"
below as "ticket").

## Context

`imbi-automations` is a CLI that applies one definition to many
projects. A definition is a directory with a `workflow.toml` file and
its prompt and template files. For each selected project the CLI checks
conditions, clones the repository, runs an ordered list of actions,
commits, and opens a pull request or pushes.

The CLI runs on a laptop. This has four costs:

1. A run uses the tokens of one person: GitHub, Imbi, the model
   provider, and Jira.
2. There is no record of a run. The result is terminal output.
3. A run for all projects holds a laptop for hours.
4. Only a person who has the CLI, the configuration, and the tokens can
   start a run.

Imbi has the parts to run this work on the server. The harness (ADR
0022) runs agent tasks in pods, with a clone of the project repository,
a GitHub App for each agent, a secrets broker, a model proxy with a
budget, and an event log. The workflow engine (ADR 0021) has triggers.

The owner of the platform decided the following on 2026-11-16:

- An automation selects any number of projects, as the CLI does.
- The scope of behavior is the scope of the CLI. No action type and no
  stage is removed.
- The server reads `workflow.toml` directories as they are.
- The engine code moves into this repository. The CLI becomes a client
  of the server.
- Credentials reach the engine through a broker. The engine holds no
  token.

## Decision

Add **automations**: a new entity whose definition is a `workflow.toml`
directory, a second engine in the harness that runs the moved
`imbi-automations` code, and runs that fan out to one agent task for
each selected project.

### Automation and its versions

An automation is organization-scoped. It has a slug, a name, a
description, an owner team, an agent, an origin (`imbi` or a source),
and versions.

- The slug rule is that of the CLI: the directory name in lower case,
  with `_` changed to `-`. The branch name
  `imbi-automations/<slug>` uses it.
- The agent gives the identity of each run: the GitHub App binding, the
  model and its budget, the pool labels, plugins, and MCP servers. The
  `plugins` and `mcp_servers` sections of the definition are added to
  those of the agent.

Storage is Postgres, for both origins:

| Table                 | Content                                                                                                                                             |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `automations`         | The fields above, and the active version                                                                                                            |
| `automation_versions` | Number, state (`draft`, `active`, `retired`), the definition as JSON, creator, activator. A sourced version also has commit SHA, path, and tree SHA |
| `automation_files`    | One row for each other file of a version that Imbi owns: path, content, hash                                                                        |
| `automation_sources`  | Repository URL, ref, path, head SHA, sync time, sync error                                                                                          |

- The definition JSON is the content of `workflow.toml` after
  validation with the engine models. It is the one form for the API,
  the editor, the activation diff, and the runner.
- An automation that a person makes in the UI has one draft version.
  Each save validates the definition and writes the draft. Activation
  makes the draft a numbered version that does not change. The next
  edit starts a new draft. A run names one version.
- The files of a sourced version stay in git. The runner fetches them
  at the commit SHA, as it fetches a marketplace.
- `workflow.toml` text is made from the JSON for display and for
  export.
- Limits: 1 MiB for a file and 10 MiB for a version.

### Sources

A source is a git repository that Imbi syncs automation directories
from. It uses the marketplace sync code (`RepositoryReader`).

- A sync reads the tree at the head SHA and finds each
  `<dir>/workflow.toml`. It saves a new version when the git tree SHA
  of the directory changed.
- A sourced automation is read-only. A person activates each new
  version after a review of the diff of `workflow.toml` and of each
  file that changed. The diff marks new callables, plugins, and MCP
  servers.
- There is no activation on merge.

### Runs

A **run** is one start of an automation version. Its inputs are those
of the CLI.

| Target                    | The `[filter]` of the definition |
| ------------------------- | -------------------------------- |
| Project ids               | Not applied                      |
| One project type          | Applied                          |
| All projects              | Applied                          |
| One GitHub repository URL | Not applied                      |

Options: include archived projects, dry run, concurrency, stop at the
first failure, cost limit, keep the workspace of a failed project, log
level.

A run has two parts:

1. **Selection.** One agent task, the planner, runs the selection code
   of the engine: list the projects of the target, apply the filter
   with its GitHub checks, and check the remote conditions of the
   definition. It has read access only and sees only the projects that
   the starter can read. It writes one row for each project to the
   API: selected, or not selected with a reason. The rows are
   idempotent.
2. **Project runs.** The API makes one **project run** for each
   selected row. A project run is an agent task with the origin kind
   `automation_run`. The engine runs the definition for that one
   project. It checks the remote conditions again.

Rules:

- A project run ends as `succeeded` (pull request opened, pushed, or no
  change), `skipped` (conditions not met), `failed`, `cancelled`,
  `conflict`, or `interrupted`.
- An automation has at most one active project run for one project.
- A lost pod starts the project run again from a clean clone only when
  the first attempt reported no external write. If it reported one, the
  project run ends as `interrupted` and a person decides.
- The limit on project runs in a run, and the limit on concurrent
  project runs in an organization, are organization settings.
- The task lists of ADR 0020 do not show tasks of the origin kind
  `automation_run` unless a person asks for them.

Differences from the CLI, on purpose:

- A push with no pull request goes to the default branch of the
  repository. The CLI pushes to `main` by name.
- A dry run gives a patch and a diff stat, not a saved directory.
- In a dry run the broker does no write. In the CLI a dry run skips
  only the push and the pull request, and `imbi` and `jira` actions
  still write.
- `docker build`, `pull`, and `push` fail with a clear message. The pod
  has no Docker daemon. `docker extract` uses a daemonless tool.
- There is no local configuration: no token fields, no `.env` file, no
  SSH clone, no local signing.

### The automation engine in the harness

Today the runner makes one `TaskRun` for each task. Its work step
builds the workspace, starts the model proxy, and runs a Claude Agent
SDK session.

- A new class, `AutomationRun`, derives from `TaskRun`. The runner
  selects the class from the kind of the task.
- `AutomationRun` keeps the session, the heartbeat, the pause and
  cancel control, the workspace and clone, the model key and model
  proxy, the event recorder, and the redactor.
- It replaces the work step. It starts the broker (below) and runs the
  engine as one long command in the executor, as uid `agent`. The task
  timeout is the limit of the command.
- The engine code is a workspace library in this repository. It is the
  source of `imbi-automations` 2.0.0b6, moved, with these changes:
  typed entry points for selection and for one project, a structured
  result, a reporter callback, a cancel check, no credentials in the
  configuration, and broker transports for its clients.
- The reporter callback becomes task events: action started, action
  finished, commit, external write, pull request, followup cycle, error
  handler.
- `claude` actions, AI commit messages, and pull request bodies use the
  model proxy of the task. All of them count against the budget of the
  task.
- `claude` actions use the session code of the engine, not
  `TaskRun.run_sdk`. The tool policy and the approval hooks of the
  agent do not apply to them. The egress rules of the pod and the
  broker scope do apply.
- A `followup` stage waits in the pod, as in the CLI. The pod stays
  for the time that CI needs. The runner asks for a new GitHub token
  when one expires.
- `callable` actions import Python packages. The runner image holds a
  fixed list of extra packages, each with a locked version and a hash.

### The broker

The engine, the shell actions, and the model run as uid `agent`. None
of them gets a token. The engine clients call the runner over a local
socket, and the runner does the operation with a credential from the
secrets broker of ADR 0022.

| Operation                      | Scope that the runner enforces                                                  | Token purpose         |
| ------------------------------ | ------------------------------------------------------------------------------- | --------------------- |
| GitHub API read                | The repositories of the task's project; the read routes below                   | `automation_read`     |
| Push a branch, delete a branch | The repository of the task; branch `imbi-automations/<slug>` or default branch  | `automation_write`    |
| Open a pull request            | The repository of the task                                                      | `automation_write`    |
| Repository settings            | The repository of the task; the three routes below                              | `automation_admin`    |
| Imbi API request               | The project of the task; the route list of agent API tokens; accountable header | The agent API token   |
| Jira: create a ticket          | The Jira integration that the agent is bound to                                 | That of the plugin    |
| Model call                     | The model proxy, with the budget of the task                                    | The model key         |

The GitHub routes are those that the engine client calls today, and no
others:

- Read: the repository, file contents, the git tree, pull requests
  with their reviews, comments, and check runs, workflow runs with
  their jobs and logs, and environments.
- Write, for each project run: `POST /repos/{owner}/{repo}/pulls`.
- Write, only for a definition that has a `github` action:
  `PUT` and `DELETE /repos/{owner}/{repo}/environments/{name}`
  (`sync_environments`) and `PATCH /repos/{owner}/{repo}`
  (`update_repository`).

Three new token purposes. The permission names are to be verified
against GitHub in the first phase:

- `automation_read`: `contents: read`, `pull_requests: read`,
  `actions: read`, `checks: read`.
- `automation_write`: `contents: write`, `pull_requests: write`,
  `workflows: write`.
- `automation_admin`: `administration: write`. The runner asks for it
  only when the definition has a `github` action. The token can do
  more than the three routes; the broker is what limits it, because
  the engine does not get the token.

The GitHub App of an automation agent must hold these permissions.
`github_write` and `workspace_checkout` do not change.

- Jira goes through the Jira plugin, which is in progress. The broker
  calls the plugin with the integration that the agent is bound to.
  This ADR adds no Jira credential of its own. Until the plugin
  exists, a `jira` action fails with a clear message; one live
  definition has such an action.
- The runner does the push itself: a fixed remote URL, a fixed refspec,
  no hooks, and a git configuration that the workspace cannot change.
  It records the head of each branch when it makes the clone, and each
  head that it pushes. Before a push or a branch delete it compares the
  remote head with the recorded heads. A branch delete is a git push
  of an empty ref, not an API call. A forced push and a branch delete
  name the head that the runner expects (`--force-with-lease`), so the
  remote refuses them when the head changed after the comparison. A
  head that Imbi did not record, or a refused push, ends the project
  run as `conflict`.
- The planner task gets the read operations only.
- A dry run makes no external write. Its project runs get the read
  operations and the model call only. The broker does not do a write;
  it records it as "would write", and the action continues. This
  includes the dry run of a draft. The rule covers the broker only: a
  shell action or a callable can still send data to a host that the
  egress rules of the pod allow.
- The accountable principal of each Imbi API request is the person who
  activated the version. Each project run checks that person again at
  its start.

The limit of this design: all processes of uid `agent` can call the
broker. The broker stops the theft of a token. It does not stop a
hostile repository or an injected prompt from an operation inside the
scope of the task.

### Permissions

| Permission                       | Allows                                                               |
| -------------------------------- | -------------------------------------------------------------------- |
| `automation:read`                | Read automations, runs, and project runs                             |
| `automation:write`               | Edit and activate an automation                                      |
| `automation:run`                 | Start, pause, cancel, and retry a run                                |
| `automation:push_default_branch` | Activate a version that has `create_pull_request = false` and clones |
| `automation_source:write`        | Add, sync, and remove a source                                       |

A person who activates a version lets it run shell commands and Python
callables in each selected repository. The UI says so at activation.

### Workflow step and CLI

- A new workflow step, `run_automation`, starts a run and waits for it.
  Ports `Succeeded` and `Failed`. It gives automations the triggers of
  ADR 0021.
- The CLI client is a set of commands in `imbi-cli`: start a run,
  follow it, read results, and send a local directory to the server as
  a draft for a dry run. `imbi-automations` gets a last release that
  points to them.

## Consequences

- One copy of the engine code. The server and the CLI client cannot
  behave differently.
- Each run has a record: who started it, the version, each project,
  each action, each commit, each pull request, and the cost.
- A run uses the identity of an agent, not the tokens of a person.
- An author cannot run the engine on a laptop. The local directory dry
  run replaces it and must exist before the CLI engine is retired.
- One pod for each project run. A `followup` stage holds its pod while
  CI runs. Runner capacity sets how fast a large run ends.
- Commits are not signed. A commit that a GitHub App pushes with git
  has no signature. A repository that requires signed commits refuses
  the branch.
- An activated definition is code that runs with the rights of the
  agent in each selected repository, and it can change CI workflows.
  The controls are the permissions, the activation review, and branch
  protection of the source repository.
- A retry of an `interrupted` project run can repeat an external write.
- `update_repository` sends the attributes of the definition to GitHub
  with no list of permitted attributes, as the CLI does. A definition
  can change the visibility or the default branch of each selected
  repository. The activation review shows "Changes repository
  settings" for such a definition.
- A model session in a `claude` action runs with the tool settings of
  the engine. An organization that limits the tools of its agents does
  not limit these sessions.
- "Resume" from a kept workspace needs an archive in object storage
  with a retention limit, and a manifest that the server owns. A copy
  of a repository is then in object storage for that time.

## Alternatives considered

- **An automation is a one-project workflow of ADR 0021, with a new
  `repository` step that implements the actions again.** Refused. It
  removed three action types and two stages from the first release, and
  a second implementation does not stay equal to the first.
- **Tokens in the engine configuration, short and narrow.** Refused. A
  shell action or an injected prompt can read them.
- **The engine runs as the runner user.** Not chosen. It needs seams in
  the engine for each shell command, each git command, and each model
  session, and file actions then run as a user that holds secrets.
- **One pod for a whole run.** Refused. There is no isolation between
  projects, and a lost pod loses all the work.
- **A new YAML definition format.** Refused. The definitions exist as
  `workflow.toml`.
