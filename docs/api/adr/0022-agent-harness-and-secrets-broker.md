# ADR 0022: Agent Harness and Secrets Broker

Date: 2026-10-13

## Status

Proposed

The plan for this work lives in the dev-environment repository's
`docs/harness-plan.md`. It replaces the owner's draft "Imbi Agent Secrets
API, revision 2".

Related: [ADR 0017](0017-autonomous-deployment-principals.md) (userless
principals), [ADR 0018](0018-ai-model-catalog.md) (model catalog),
[ADR 0019](0019-apache-iggy-message-streaming.md) (Iggy),
[ADR 0020](0020-agent-task-contract.md) (agent tasks),
[ADR 0021](0021-workflow-contract.md) (workflows), scheduler
[ADR 0002](../../scheduler/adr/0002-no-credential-store-in-v1.md) (no
credential store) and
[ADR 0003](../../scheduler/adr/0003-no-local-token-minting-bridge.md) (no
local token minting).

## Context

ADR 0020 defines the agent task contract: tasks, sessions, events, usage,
human requests, and control state. It leaves out the process that runs an
agent ("the harness") and how work gets to it. ADR 0021 defines workflows
and expects an `agent` step when a harness exists. Nothing runs an agent
today.

Five facts shape this decision:

1. **Agents change real systems.** They clone repositories, push, open pull
   requests, tag, and publish releases. They need credentials for systems
   outside Imbi.
2. **The model is not trusted with credentials.** A model can be steered by
   the text it reads, including webhook payloads. Anything the model can
   read, it can repeat or send.
3. **Imbi stores no secret material.** Scheduler ADR 0002 keeps credentials
   out of Imbi's databases. Integrations keep encrypted plugin credentials,
   but no new store of secret values is wanted.
4. **One SDK process tree runs model and tools together.** The Claude Agent
   SDK (Python) starts the Claude Code CLI as a subprocess. The CLI runs the
   model's tools, such as `Bash`, in its own process tree and with its own
   environment. In-process SDK MCP tools run in the parent Python process.
5. **The SDK loads plugins from local paths only.** A marketplace plugin
   must be on disk before the session starts. A plugin that fails to load
   is skipped without an error.

## Decision

### Runner pool and dispatch

A runner is a pod that runs agent tasks. Runners are in pools, as CI
runners are.

- A **pool** belongs to the platform. It has a name, labels, an optional
  organization allowlist (empty means all organizations), and a service
  account. Each pool is a fixed-size Kubernetes Deployment with its own
  image, built from the base runner image. Pools run in their own
  namespace.
- **Dispatch is pull.** A runner registers, then long-polls a claim
  endpoint on imbi-api. Imbi selects the oldest `queued` root task whose
  agent is enabled, whose agent's required labels the runner has, whose
  organization the pool allows, and whose agent is under
  `max_concurrent_tasks`. It selects with `FOR UPDATE SKIP LOCKED`. Iggy is
  not a work queue.
- **A chain is the unit of work.** A chain is a root task and all of its
  child tasks (origin kind `task`). A claim pins the whole chain to one
  runner until every task in it has a terminal outcome. Only that runner
  can claim the chain's child tasks. All tasks in a chain share one
  workspace. A child task for another agent runs as a second SDK instance
  with that agent's identity and configuration. Imbi refuses to create a
  child task that needs a label the chain's runner does not have.
- **Blocked chains keep their runner.** A task waiting on a person holds
  its pod. The runner ends the SDK query and resumes the session when the
  request is resolved. `task_timeout_seconds` counts blocked time.
- **One chain per pod.** When a chain ends, the runner releases its
  secrets, closes its sessions, reports that it finished, and deletes its
  own pod. The ReplicaSet starts a clean pod. Nothing from one chain stays
  for the next.
- **Leases and fencing.** A runner heartbeats a lease. A runner that
  loses only its connection to imbi-api can still reach GitHub, so lease
  expiry alone must not make its chain claimable. Fencing has three parts:
  1. **The runner fences itself.** If the runner cannot renew its lease
     before a safety margin ahead of expiry, it stops every SDK instance,
     kills every executor child, and exits. The margin is larger than the
     time it needs to stop.
  2. **imbi-api fences the credentials.** At expiry, imbi-api marks the
     runner offline. It revokes every secret resolution and provider lease
     of that runner. Revocation of a GitHub installation token goes from
     imbi-api to GitHub, so it works while the runner is cut off. It also
     invalidates the runner, executor, and agent tokens. Each claim carries
     an attempt number, and the harness endpoints refuse a write from an
     older attempt.
  3. **imbi-api waits, then requeues.** imbi-api makes the chain claimable
     only after revocation succeeds and a grace period has passed. The grace
     period is longer than the runner's stop time plus the allowed clock
     skew. Then it writes an `attempt_marker` event to each open task in
     the chain and puts the chain back in the queue. If a provider
     revocation fails, the chain stays fenced and shows as stuck until an
     operator acts.

  A test covers a partition between the runner and imbi-api only, with
  GitHub still reachable. The old runner's next GitHub write fails with
  `401`, and the old runner exits before the new attempt starts.

New Postgres schema `harness`: `pools`, `runners`, and the chain pin. It
follows the `agent_runtime` and `workflow_runtime` pattern.

### Runner identity and tokens

| Credential | Held by | Can |
|---|---|---|
| Pool credential (service account client credential, from a Kubernetes Secret) | Runner | Register a runner only |
| Runner credential (returned by registration) | Runner | Heartbeat, claim, chain claim, finish |
| Executor credential (returned by registration) | Executor | Materialize and release resolutions assigned to this runner |
| Agent token (returned by a claim, one per task's agent) | Runner | The ADR 0020 harness endpoints and secret resolution requests, for tasks in this chain only |

imbi-api mints every token. An agent token is a JWT for the agent's
service principal (ADR 0020), with audience `imbi-harness` and a `chain`
claim. Routes outside the harness refuse that audience. Runners never hold
`IMBI_AUTH_JWT_SECRET`, so a runner cannot mint a token (scheduler
ADR 0003).

### Pod isolation

Each runner pod has two containers from the same image and three OS
users.

| Process | Container | User | Holds |
|---|---|---|---|
| Runner: claim loop, SDK host, privileged tools, model proxy | `runner` | `runner` | Pool, runner, and agent tokens; resolution handles; model key |
| Executor: materializes secrets, starts credentialed commands | `executor` | `executor` | Executor credential |
| Claude Code CLI and its tools | `runner` | `agent` | Nothing |
| Commands run with a secret | `executor` | `agent` | Only that command's secrets |

- The SDK starts the CLI as `agent` (`ClaudeAgentOptions.user`).
- The containers do not share a process namespace. Credential files are in
  per-container volumes with mode `0700`.
- The executor socket allows only the runner. It is in a group that does
  not contain `agent`, and the executor checks the peer uid.
- **The Kubernetes service account token.** The pod sets
  `automountServiceAccountToken: false`. A projected service account token
  is mounted in the `runner` container only, owned by uid 0 with mode
  `0400`. The runner process runs as `runner`, so it cannot read the file
  during the chain. It can switch back to uid 0, because it keeps uid 0 as
  its saved uid (see below). At the end of the chain it does this to read
  the token and delete its own pod. `agent` processes have no capabilities
  and a different uid, so they cannot read the token. That token is the
  only one that can delete pods.
- Kubernetes gives no added capability to a non-root process. Both
  containers therefore start as uid 0 with only `SETUID` and `SETGID`,
  with `allowPrivilegeEscalation: false`, a read-only root filesystem, and
  `RuntimeDefault` seccomp. Each process then sets its effective uid to its
  own user. It keeps uid 0 as its saved uid, which it needs to start
  `agent` processes. A process with saved uid 0 cannot be read through
  `/proc` by `agent`. The namespace runs at Pod Security level Baseline.
- Each privileged tool runs in the runner process as an in-process SDK MCP
  tool. The model gives it a secret reference, a purpose, and other
  values that are not secret. It returns only a resolution id, a state,
  and an expiry. Handles never pass through the SDK.

All containers in a pod share one network namespace, so user ids do not
separate network access. Credentials are the control.

### Agent configuration

- **Organization base configuration.** A versioned `AgentPlatformConfig`
  per organization sets:
  - the model upstream (Anthropic API or a LiteLLM gateway, and the secret
    reference of its key)
  - allowed marketplaces and default plugins
  - built-in tool allow and deny lists
  - permission mode and sandbox settings
  - a base system prompt
  - hooks
  - origin rules: tools that need approval when the task's origin is not a
    person

  An agent can only narrow these settings. A task pins the configuration
  version next to its agent and prompt versions.
- **Marketplaces** are Claude Code plugin marketplaces. An organization
  registers one by git URL. imbi-api syncs its
  `.claude-plugin/marketplace.json` into a plugin catalog. When an agent
  version enables a plugin, Imbi pins the marketplace commit SHA in the
  version. The runner clones the marketplace at that SHA and passes the
  plugin path to the SDK. If a pinned plugin does not appear in the SDK's
  init message, the task fails.
- **New agent fields:** required labels, plugins, a GitHub App binding, and
  the secret references the agent may request.
- **Identity bundle.** A claim returns, for each task:
  - the task
  - the pinned agent version and the rendered prompt
  - the merged configuration
  - each plugin's marketplace URL and SHA
  - the project's repositories

  imbi-api merges the configuration, so every runner applies the same
  rules. The bundle contains no secret material.

### Model proxy

The runner runs a model proxy on loopback. The CLI gets the proxy's
address and a placeholder key.

- The proxy gets the real key as a secret resolution (purpose
  `model_inference`) and forwards requests to the configured upstream.
- It reads token usage from each response and sends the ADR 0020 usage
  report. imbi-api prices the tokens from the model catalog.
- When the task budget is spent, it refuses new calls.

A model reached through LiteLLM needs a catalog entry. Without one, its
usage is reported as unpriced.

### Tool policy

The runner applies the agent's tool configuration in `can_use_tool` and
`PreToolUse`:

1. It denies tools that are not configured.
2. A tool that needs approval opens an ADR 0020 `approval` request and
   blocks the task.
3. A tool with a rate limit asks imbi-api, which counts per agent, tool,
   and period across all runners.
4. A tool that declares an environment argument is refused for an
   environment the agent may not use.

Every call, allowed or denied, writes a `tool_call` event.

### Task event changes

- Task events include thinking blocks (as `turn` events with
  `kind: thinking`) and full tool results.
- The inline payload limit for `turn` and `tool_call` events becomes 1 MiB.
  A larger payload is sent as continuation events with the same call id and
  `part` and `parts`. Replies and resolutions keep the 64 KiB limit.
- The runner redacts known secret formats, and every value the executor
  delivered, before it appends an event.
- Text that does not come from a person in Imbi goes into labeled
  `untrusted` tags with a fixed system prompt rule. The origin rules above
  are the control. The tags only help.

### Secrets broker

imbi-api brokers secrets that external systems hold. It stores no secret
values.

- **Resources**, all owned by one organization:
  - **Providers:** an adapter with explicit capabilities.
  - **Bindings:** a logical reference `secret://<scope>/<path>[#<field>]`
    mapped to a provider location, with allowed fields, delivery modes,
    and maximum lifetime.
  - **Grants:** exact agent ids, optional project ids, bindings, purposes,
    delivery modes, and maximum lifetime.
  - **Resolutions:** a short-lived permission for one task, one runner,
    and one binding.
- **Flow.**
  1. The runner asks for a resolution with its agent token.
  2. imbi-api takes the agent, project, organization, and runner from the
     token and the chain pin. The request cannot set them.
  3. Exactly one active grant must allow the whole request. Otherwise the
     request is denied.
  4. imbi-api returns a handle. The handle has at least 256 random bits,
     is stored only as a keyed hash, and is bound to the full context.
  5. The runner sends the handle to the executor.
  6. The executor materializes the handle once, with a nonce, immediately
     before it starts the command. Imbi checks the current state again at
     this point.
  7. The executor delivers the secret by file descriptor, stdin, a private
     file, or the child environment. It never delivers a secret as a
     command argument.
  8. The executor filters the command output and releases the resolution
     when the command exits.
- **Rules.**
  - Secret material is never written to a database, queue, log, trace,
    metric, error, or URL.
  - Materialization responses are `no-store`, and body capture is off for
    that route.
  - Disabling a provider, binding, or grant stops new resolutions and makes
    unused handles invalid at once.
  - Release and provider revocation are separate results. A failed
    revocation stays visible.
- **Setup secrets.** The runner can ask for a resolution without a model
  request, for purposes such as `workspace_checkout` and
  `marketplace_fetch`. Grants control these like any other request.
- **`run_with_secret`.** The model runs a command of its choice with named
  secrets, for example `gh` with `GH_TOKEN`. This is deliberate: most
  GitHub automation at AWeber uses `gh`. The command runs as `agent` with a
  clean environment.
- **Providers in this version:**
  - `fake` (tests)
  - `aws_secrets_manager` (static and rotated secrets, workload identity,
    no access keys in configuration)
  - `github_app` (dynamic)
- **Audit.** Each step writes an audit event through Iggy to the ClickHouse
  table `secret_audit_events`, with no TTL. Each resolution also writes a
  task event. Audit and task events carry ids, purpose, and result, never
  material, handles, or lease ids.

### GitHub Apps

Each agent has its own GitHub App, so its commits, pull requests, and
releases show as `<agent>[bot]`.

- A `github_app` binding names the app id, the installation id, the GitHub
  host, and the secret reference of the App's private key.
- `resolve` mints an installation token for the task's project
  repositories, with permissions set by purpose:
  - `contents: read` for checkout
  - `contents: write`, `pull_requests: write`, and `issues: write` for
    `github_write`

  The App's own permissions are the upper limit.
- Release revokes the token. A token lasts at most one hour.
- In this version a person creates and installs the App by hand.

### Workflow `agent` step

A new step type creates an agent task and waits for its outcome. As
ADR 0021 requires, the task keeps the run's root origin (`human`,
`schedule`, or `webhook`) and records the workflow run id and node `key`
in `origin`. The idempotency key is `<run_id>:<node_key>`. The step's
output is the outcome, the reason, and the agent's summary. Cancelling the
run cancels the task.

### Permissions

| Permission | Allows | Holder |
|---|---|---|
| `harness_pool:read` | Read pools and runners. Organization members see only pools that serve their organization. | Organization administrators |
| `harness_pool:write` | Create and change pools | Platform administrators |
| `agent_platform_config:write` | Change the organization base configuration and marketplaces | Organization administrators |
| `secret_provider:read`, `secret_provider:write` | Providers, including the test action | Organization administrators |
| `secret_binding:read`, `secret_binding:write` | Bindings, including validation | Organization administrators |
| `secret_grant:read`, `secret_grant:write` | Grants and grant evaluation | Organization administrators |
| `secret_resolution:read`, `secret_resolution:manage` | Read resolutions; release them and revoke provider leases | Organization administrators, auditors (read) |
| `secret_audit:read` | Read secret audit events | Organization administrators, auditors |

Runner, executor, and agent credentials are not permissions. They are
token types that only the harness routes accept.

### Not decided here

- Network egress control. This version has open egress.
- Release of a blocked chain's pod with saved state.
- Pod autoscaling on queue depth.
- Automatic GitHub App setup.
- Object storage for plugin snapshots and large artifacts.
- Vault, lease renewal, pattern grants, and approval workflows for secrets.
- Escalation policy (ADR 0020).

## Consequences

- **A token can leave the pod.** `run_with_secret` with open egress lets a
  model-chosen command send its token out while the command runs. The
  token covers only the task's repositories and purpose, lasts at most one
  hour, and is revoked when the command exits. An egress allowlist is the
  later control.
- Output filtering catches exact values and common encodings only. It is
  defense in depth.
- A blocked chain holds a pod with nothing to do. Pools are fixed size, so
  many blocked chains delay other work.
- A crash or eviction loses the workspace. The chain starts again with an
  `attempt_marker`. Side effects already done (a pushed branch, an opened
  pull request) stay, and the agent finds them on the next attempt.
- Runner pods need Pod Security level Baseline and a Role that can delete
  pods in the runner namespace. A compromised runner process, not the
  model's tools, can delete other runners in that namespace.
- Fencing makes an expired chain wait for revocation and a grace period
  before another runner can claim it. A failed provider revocation keeps
  the chain stuck until an operator acts.
- Each agent that uses GitHub needs a GitHub App created by hand.
- A new app (`imbi-harness`), a new namespace, and a Helm chart change.
  The Helm chart has no CI coverage, so `helm template` is checked by hand.
- `agent_task_events` rows can be up to 1 MiB, and tasks write more
  events. ClickHouse storage for task events grows faster.
- Secret audit events have no TTL.

## Alternatives Considered

### Iggy as the work queue

Rejected. Postgres already holds task state, concurrency limits, and the
budget. A second queue would need to agree with it. Iggy consumer groups
have also lost their partition to a dead member after restarts.

### Long-lived runner pods with in-process cleanup

Rejected. Removing a workspace does not remove processes, caches outside
it, or kernel state. Deleting the pod is complete and simpler.

### Typed GitHub tools in place of `run_with_secret`

Fixed commands (`git_push`, `open_pull_request`, `create_release`) keep the
token away from model-chosen commands. Rejected for this version because
existing GitHub automation uses `gh` with `GH_TOKEN`, and a typed tool for
each action does not scale. The risk is recorded above.

### Imbi stores plugin snapshots in object storage

Runners would need no git access for plugins, and each task would record
exact plugin bytes. Deferred. Object storage needs the same access model as
GitHub before runners use it.

### One container with three users

Rejected. It needs a root supervisor, and processes in one container can
see each other in `/proc`. Two containers give process separation with the
same image.

### The agent in a separate pod

Network separation for the model's tools. Deferred. With open egress it
adds little, and the SDK needs the CLI as a local subprocess, so a remote
transport would be needed.
