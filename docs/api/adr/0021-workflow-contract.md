# ADR 0021: Workflow Contract

Date: 2026-10-12

## Status

Proposed

The plan for this work lives in the dev-environment repository's
`docs/workflows-plan.md`. The UI design is the "Workflow Builder" file in
the Agent Management claude.ai/design project.

Related: [ADR 0016](0016-delegated-execution-for-scheduled-jobs.md)
(scheduled execution), [ADR 0017](0017-autonomous-deployment-principals.md)
(userless principals and deployments), [ADR 0020](0020-agent-task-contract.md)
(agent tasks).

## Context

A workflow chains a trigger to steps: wait, ask a model to choose a branch,
deploy, roll back, send a message, and later dispatch to an agent. People
build workflows on a canvas and expect them to run unattended on a
schedule, on a webhook, or on request.

Four facts shape the contract:

1. **Most step types in the design have no backend.** Imbi cannot read
   Sentry, Prometheus, or Kubernetes signals, send Slack messages, open pull
   requests, create a human task, run a script in a sandbox, or call an
   arbitrary URL. No harness runs agents (ADR 0020). The contract must let
   step types arrive one at a time.
2. **Runs are hot and transactional.** A run changes state on every step.
   Like agent tasks, runs do not belong in the AGE graph, and AGE is
   scheduled for removal in 3.0, so definitions do not belong there either.
3. **Unattended runs need a principal.** Delegated run-as-user execution
   (ADR 0016) is not implemented. Userless principals can drive deployments
   only within the bounds of ADR 0017.
4. **A workflow aggregates authority.** Whoever edits a workflow decides
   what its principal does. Without a check, editing a workflow grants
   indirect access to every step type it can use.

## Decision

### Definitions are relational and versioned

A new Postgres schema, `workflows`, managed with the same tooling as
`agent_runtime`, holds definitions:

| Table | Holds |
|---|---|
| `workflows` | One row per workflow: organization, slug, name, description, owner team, status, `latest_version`, `active_version`, activated by, activated at |
| `workflow_versions` | One immutable row per saved version: graph, settings, validation result, author, created at |
| `trigger_bindings` | One row per trigger of the active version: the scheduler task or gateway rule it needs, sync state, last error |

Rows refer to graph nodes (organization, team, agent, project, user) by id.
Application code validates those ids on write.

`status` is `draft`, `active`, or `paused`. Save creates a version and
moves `latest_version`. A version never changes. Triggers start runs of
`active_version` only, so a saved but not activated version never runs. A
run pins the version it started on, so editing a workflow never changes a
run in progress.

### The graph

A version's graph is JSON validated by a Pydantic model:

- **Node**: `id`, `key`, `type`, `title`, `position`, `params`, `join`.
  - `key` is unique in the workflow, matches `^[a-z][a-z0-9_]*$`, and names
    the node's output in references. It defaults to a slug of the title and
    keeps its value when the title changes.
  - `join` is `any` or `all` (below). Default `any`.
- **Edge**: `from` (node id), `port` (output index), `to` (node id).

Each step type declares its ports. A type with one output has one unnamed
port. A branching type names its ports: deploy has `Succeeded` and
`Failed`; a model decision has one port per configured branch.

### Step types are a registry

Each step type is one module in a registry shared by imbi-api and the
engine. It declares:

| Field | Meaning |
|---|---|
| `type`, `category`, `label` | Identity and palette group |
| `trigger` | True for trigger types. A trigger has no input port. |
| `ports` | Fixed names, or a function of `params` |
| `params_schema` | JSON Schema for `params`; drives the inspector form |
| `output_schema` | JSON Schema for the step's output |
| `sample_output` | Output used by test runs |
| `required_permissions` | Permissions the step needs, as a function of `params` |
| `side_effect` | True when the step changes something outside the run |

The API serves the registry. The UI builds the palette and the inspector
forms from it. A type that is not in the registry fails validation, so a
step type exists only when the engine can execute it.

v1 types: `manual`, `schedule`, `webhook` (triggers), `wait`,
`model_decision`, `email`, `deploy`, `rollback`.

### Validation

Save accepts a graph with warnings. Activation requires a graph with no
errors and no warnings. Checks:

- Every node type is in the registry, and its `params` match
  `params_schema`. A missing required parameter is a warning.
- The graph has at least one trigger.
- No edge enters a trigger.
- No edge leaves a port the node does not have.
- The graph has no cycles. v1 workflows are directed acyclic graphs.
- Every node is reachable from a trigger.
- Every reference names a node `key` upstream of the node that uses it.
- Size limits: 100 nodes, 200 edges, 64 KiB of graph JSON.

### Runs

A second Postgres schema, `workflow_runtime`, holds runs:

| Table | Holds |
|---|---|
| `runs` | One row per run: workflow, pinned version, origin, trigger payload, concurrency key, status, timestamps, error, `cancel_requested`, `last_seq`, `log_archived_at` |
| `step_runs` | One row per node per run: status, attempt, input, output, error, chosen port, timestamps |
| `run_events` | A buffer of run events for runs that are not yet archived |
| `leases` | One row per claimed run: worker id, `expires_at` |

imbi-api owns both schemas and applies them on startup. The engine reads
and writes `workflow_runtime` directly.

Run status: `queued`, `running`, then one terminal status: `succeeded`,
`failed`, `cancelled`, or `timed_out`.

Step status: `pending`, `running`, then one terminal status: `succeeded`,
`failed`, `skipped`, or `cancelled`.

A run and the step records that change with it commit in one transaction.

### Execution

The engine is a new app, `imbi-workflows`. It is a worker with a health
endpoint and no public API.

- **Claiming.** The engine claims a claimable run with
  `FOR UPDATE SKIP LOCKED` and writes a lease with an expiry, as the
  scheduler does. A run whose lease expires is claimable again.
  `LISTEN/NOTIFY` wakes the engine early. It is a hint only: the engine
  always polls for claimable runs, so a lost notification delays a run but
  never loses it.
- **Order.** A step is ready when its join condition is met. The engine
  runs ready steps, records each result, and repeats until no step is
  ready.
- **Branching.** A branching step activates one port. Every edge from its
  other ports is inactive. A step whose incoming edges are all inactive is
  `skipped`, and its outgoing edges are inactive in turn.
- **Joins.**
  - `any`: the step runs once, when the first active incoming edge
    arrives.
  - `all`: the step runs when every incoming edge is active or inactive
    and at least one is active.
  - Validation warns when an `any` join has two incoming edges that can
    both be active in one run, because the second arrival is ignored.
- **Failure.** An error (an exception, a timeout, a `5xx`) uses the step's
  retries first. A failed outcome that the step reports (a deployment that
  failed) is not retried. After either, the step takes its `Failed` port
  when its type has one. Otherwise the run fails: steps already running
  finish and their results are recorded, every pending step is
  `cancelled`, and the workflow's failure policy runs.
- **Unknown outcomes.** The engine records an attempt as `running` before
  it makes the call. When it finds a `running` attempt with no result
  (after a crash or a timeout), it asks the step type to reconcile: deploy
  and rollback look up the deployment by idempotency key. A type that
  cannot reconcile and is not idempotent fails the step with
  `outcome_unknown` and does not retry.
- **At least once.** A crash between a side effect and its record repeats
  the step. Each side-effecting step passes the idempotency key
  `<run_id>:<node_key>` to the API it calls. The key does not change
  between attempts, so a repeat does not repeat the effect where the API
  supports keys.
  Steps whose API takes no key record that they are not idempotent, and
  the registry marks them.
- **Retries and timeouts.** Each node may set a timeout and a retry count.
  Retries use exponential backoff. Defaults come from the step type.
- **Max run time.** Counted from run creation. A run that passes it is
  `timed_out`, and its running step is `cancelled`.
- **Cancel.** A person sets `cancel_requested`. Cancel is cooperative: the
  engine checks it before each step, lets a running step finish and
  records its result, marks pending steps `cancelled`, and closes the run
  as `cancelled`. A failed run closes the same way, after its running
  steps finish.

### Concurrency

Workflow settings choose a concurrency mode:

| Mode | Key |
|---|---|
| `unlimited` | None |
| `one_at_a_time` | The workflow id |
| `one_per_key` | A reference evaluated against the trigger payload, for example `{{ trigger.service }}` |

A run whose key matches a running run waits in `queued`, in creation
order.

Validation requires every `manual` trigger to declare the input that
`one_per_key` references, and refuses `one_per_key` for a workflow with a
`schedule` trigger. A webhook payload is known only at run time: a run
whose key resolves to nothing fails at once with `concurrency_key_missing`.

### References

Parameters use the `{{ … }}` syntax, rendered by the existing sandboxed
Jinja environment (`imbi.common.prompts.rendering`).

- Scope: `trigger` (the payload or the manual inputs) and the output of
  each upstream node by `key`.
- A parameter whose whole value is one reference resolves to the typed
  value. Any other parameter renders as a string.
- A reference to a node that was `skipped` resolves to nothing.
- Secrets are never parameter values. A parameter may name a secret held by
  an Integration. Resolved secret values are redacted from step input,
  output, and errors before they are stored.

### Triggers

| Trigger | Starts a run by | Origin |
|---|---|---|
| `manual` | `POST .../workflows/{slug}/runs` with inputs typed by the trigger | `human`, with the user id |
| `schedule` | A scheduler task with an `ApiTarget` to the same endpoint, created on activation and disabled on pause | `schedule`, with the scheduler task id |
| `webhook` | The gateway built-in action `start_workflow`, which requires a verified signature and takes a CEL filter | `webhook`, with the webhook id and the delivery id |

Every trigger passes an idempotency key: the request's key for `manual`,
the scheduler run id for `schedule`, the delivery id for `webhook`. The key
is unique per organization, origin kind, origin principal, and key, as in
ADR 0020. A repeat returns the first run.

A `webhook` trigger node names an existing gateway Webhook and a CEL
filter. Its binding is a `start_workflow` rule on that Webhook. The
design's free-form "Gateway path" is not used: the path belongs to the
Webhook.

Trigger bindings are desired state. Activation and pause commit in
Postgres only: the workflow's status, `active_version`, and one
`trigger_bindings` row per trigger with the scheduler task or gateway rule
it needs. A reconciler then writes the scheduler and gateway to match, and
records each binding as `synced` or `failed` with the error. It runs after
each commit and on a schedule. The editor shows a binding that is not
`synced`.

The scheduler and the gateway call the same run endpoint, which starts
runs of the current `active_version` only. A binding that is out of date
for a short time therefore never runs an old version; at most it fires a
trigger the new version removed, and that call is refused with `409`.

A paused workflow starts no runs. The run endpoint returns `409`. The
gateway action records that delivery as no effect and does not ask the
sender to retry.

### Principal and authority

Runs execute as one service account, `imbi-workflows`.

- Side effects that imbi-api already guards (deploy, rollback) go through
  the API with that service account's client-credentials token. The
  bounds of ADR 0017 apply unchanged: the service account needs
  `integration:act-as-service`, membership in the workflow's organization,
  and a target environment with `allow_autonomous`. It is not an internal
  principal and gets no exemption.
- **Activation checks the person.** The person who activates a workflow
  must hold every permission in the `required_permissions` of every node.
  Without them, activation fails with the missing permissions. The
  activating person is recorded on the workflow.
- **Every activation checks.** Saving a version never changes what runs.
  Making a new version the `active_version` runs the same check against
  the person activating it. A person who fails it can still save versions;
  the workflow keeps running its current `active_version`.
- **Authority does not outlive the activator's.** When a run starts, the
  engine checks that the activating person is still active and still
  holds the permissions the activation check required. When they are not,
  the run fails with `activator_lacks_permission` and the workflow is
  paused. Someone with the permissions must activate it again.
- **The engine checks again at run time.** A step whose call returns
  `403` fails with that error. The engine does not retry it.

Step types with authority of their own follow the same rule. An `email`
step sends only to Imbi users and teams in the workflow's organization,
never to an arbitrary address.

### Model decisions

A `model_decision` step calls `typesafe.decide` with a decision model from
the AI Model catalog (ADR 0018) and the step's branch labels as choices.

- The prompt is rendered with the references above.
- The output records the choice, its probability, and the model's
  reasoning when the model returns one.
- When the top probability is below the step's minimum confidence, the
  step takes its last port.
- Only `decision` models from the catalog are offered. Generative models
  give no probabilities, so the minimum confidence would mean nothing.

### Test runs

A test run is a simulation. It does not create a `runs` row.

- The API walks the graph from a trigger the person picks. Each node
  returns its type's `sample_output`.
- A branching node takes its first port, or a port the person picks.
- It makes no model call, sends nothing, deploys nothing, resolves no
  secret, and creates nothing.
- The response is the ordered list of nodes with their outputs and chosen
  ports, and the list of skipped nodes.

### Run history: Postgres is the state; ClickHouse is the durable log

This follows ADR 0020.

- **Events.** Every change to a run or a step writes a `run_events` row in
  the same transaction: `run.created`, `run.started`, `step.started`,
  `step.succeeded`, `step.failed`, `step.skipped`, `step.cancelled`,
  `run.closed`. Each has a stable `event_id` and a per-run `seq` that
  starts at 1 and has no gaps. A step event carries everything the history
  view shows: node `key`, type, and title as they were in the pinned
  version, attempt, timing, chosen port, error class, and the redacted
  input and output. History never needs the workflow version.
- **Publishing.** After commit, each event is published through Iggy to the
  ClickHouse table `workflow_run_events` (ReplacingMergeTree on
  `event_id`, ordered by organization, run, `seq`). A run summary is
  published to `workflow_runs` with the two-row pattern of
  `scheduler_runs`: a row when the run starts and a terminal row with a
  higher `_row_version` (ReplacingMergeTree on `_row_version`, ordered by
  organization, workflow, run).
- **Queries.** Every read of `workflow_runs` takes the latest row per run
  (`argMax` by `_row_version`, or `FINAL`). A plain `count()` double-counts
  runs whose rows have not merged. Tests cover reads over unmerged parts.
- **Archive.** A sweep republishes any missing event. ClickHouse has every
  event when the distinct count of `seq`, its minimum (1), and its maximum
  all match the run's `last_seq`. When a run is closed, ClickHouse has every
  event, and its terminal `workflow_runs` row is readable, the sweep
  deletes the run's `run_events` and `step_runs` rows and sets
  `log_archived_at`.
- **The `runs` row stays.** It is small and holds the archive marker, the
  origin, and the outcome, so the API always knows where to read a run's
  log, and audit references never depend on ClickHouse alone.
- **Reads.** Run detail reads Postgres before archive and ClickHouse after.
  The list page's runs in 30 days and last outcome read `workflow_runs`.
  Live views read Postgres only.
- **Retention.** No TTL to start, as for `agent_task_events`. Both
  ClickHouse tables carry `run_created_at` on every row, so a later TTL can
  expire on a column every row shares, never with `DELETE WHERE`, and
  deduplication cannot bring back an expired row. Erasure of a person's data in run payloads follows the same
  redaction rules as ADR 0020 (CC8): payloads are redacted before they are
  published.
- **Streams.** Adding both streams means updating `TOPICS`,
  `clickhouse/schemata.toml`, and `compose.ci.yaml` `IGGY_TOPICS`, and
  restarting `iggy-connect` in each environment after the first deploy.

### Agent tasks from workflows

When the `agent` step type ships, an AgentTask it creates records the root
origin of the run (`schedule`, `webhook`, or `human`) and the causation
chain: the workflow run id and the node `key`. It does not replace the root
origin with a `workflow` kind.

### Permissions

| Permission | Allows |
|---|---|
| `workflow:read` | List and read workflows, versions, and runs |
| `workflow:create` | Create a workflow |
| `workflow:write` | Edit, activate, and pause a workflow |
| `workflow:delete` | Delete a workflow with no running runs |
| `workflow:run` | Start a manual run, start a test run, cancel a run |

### Not decided here

- Step types beyond v1: dispatch to agent, signal gates and signal waits,
  Slack messages, pull requests, human tasks, script steps, HTTP requests.
  Each gets its own decision.
- Approvals inside a run (the design's "Required in production").
- Escalation of failed runs beyond "notify the owner team" and "do nothing".
- Cycles and loops.

## Consequences

- A new app means a new image target, a new Helm `service.mode`, a
  service account, and dev-environment entries. The Helm chart has no CI
  coverage, so `helm template` is checked by hand for the new mode.
- Two processes write `workflow_runtime`: imbi-api creates and cancels
  runs; the engine executes them. Schema changes must keep both working
  during a rolling deploy.
- Run history has two homes over time: Postgres until archive, ClickHouse
  after. The run endpoints hide this. A ClickHouse outage delays archive
  and the list page's run counts. It does not stop runs or the live view.
- `workflow_run_events` and `workflow_runs` have no TTL. They grow with run
  volume. A retention decision is needed before volume makes them
  expensive.
- Trigger bindings are eventually consistent with activation. A binding
  that fails to sync shows in the editor and leaves that trigger idle; it
  never runs a version that is not active.
- No workflow can deploy to an environment until an operator sets
  `allow_autonomous` on it and grants the service account
  `integration:act-as-service` and organization membership.
- A workflow keeps running when the person who activated it leaves. Their
  user id stays on the workflow for audit.
- Step types without idempotent downstream APIs can repeat an effect after
  a crash. The registry marks them, and the editor shows it.
- Agents gain a delete check: an agent used by an active workflow version
  cannot be deleted.
