# ADR 0020: Agent Task Contract

Date: 2026-10-07

## Status

Accepted

The plan for this work lives in the dev-environment repository's
`docs/agent-runtime-plan.md`. Behavioral requirements are in
`docs/agentic-platform-requirements.md` in the same repository; ids such as
`F4` and `CC6` refer to that document.

Related: [ADR 0017](0017-autonomous-deployment-principals.md) (userless
service principals), [ADR 0018](0018-ai-model-catalog.md) (model pricing),
[ADR 0019](0019-apache-iggy-message-streaming.md) (Iggy to ClickHouse).

## Context

Imbi stores agent definitions (`Agent`, `AgentVersion`) but has no record of
agent work. The Tasks, Usage, and Dashboard pages of the Agents area need
one: what an agent is working on, its state, the exchange between people and
the agent, the tools it called, and what it cost.

The process that runs agents (the harness) is a separate design. This ADR
defines only the contract between Imbi and any harness, and between Imbi and
the people who watch and steer agent work. It does not decide how work is
dispatched to a harness, which tools agents get, how tool calls are gated, or
how escalation works. Each of those gets its own decision.

Three facts shape the contract:

1. **Task state is hot and transactional.** Status, control state, open
   requests, and budgets change many times per task and are read on every
   harness turn. The AGE graph is a poor fit, and the move from AGE to
   relational tables is deferred.
2. **The history must be complete and permanent.** Every exchange between
   people and agents is the audit trail (F10, N6), and the Usage page
   aggregates over all of it. ClickHouse, fed through Iggy, already holds
   Imbi's durable, queryable history.
3. **Budgets need an authority that is never behind.** The Iggy to
   ClickHouse path is asynchronous. A budget read from it can be wrong at the
   moment it matters.

## Decision

### Postgres is the state; ClickHouse is the durable log

A new Postgres schema, `agent_runtime`, managed with the same tooling as the
scheduler store, holds task state:

| Table | Holds |
|---|---|
| `tasks` | One row per task: identity, status, control state, pinned versions, origin, owner, budget, totals, `log_archived_at` |
| `sessions` | One row per harness execution period of a task |
| `events` | A buffer of events for tasks that are not yet archived |
| `requests` | Feedback and approval requests and their resolution |
| `budget_ledger` | One row per usage report, with the rates used |
| `task_id_sequences` | One counter per organization for short ids |

Rows refer to graph nodes (organization, agent, project, user, service
account) by id. Application code validates those ids on write.

Every event is published through Iggy to the ClickHouse table
`agent_task_events` after its Postgres transaction commits. Every usage
report is published to `agent_usage`. ClickHouse is the permanent record.

A task's state change and the event that records it commit in one
transaction. Nothing changes a task without writing an event.

### Archive moves the log out of Postgres

A sweep runs on a schedule. For each task it compares the Postgres events
with ClickHouse and republishes any missing event. ClickHouse has every
event when its number of distinct sequence numbers and its highest
sequence number both equal the task's `last_seq`: sequences start at 1
and have no gaps, so only the full set `1..last_seq` gives that result.
Duplicate rows that ReplacingMergeTree has
not merged yet do not change a distinct count. When a task has a terminal
outcome and ClickHouse has every event, the sweep deletes the task's
Postgres events and sets `log_archived_at`.

The events endpoint reads Postgres for a task that is not archived and
ClickHouse for one that is. Callers see one log.

The sweep replaces a transactional outbox. Iggy publishing stays direct,
as for every other Imbi producer. Nothing live reads ClickHouse: harness
polling, the UI's live view, and budgets read Postgres.

### Entities

**`AgentTask`** is the durable unit of work on one subject by one agent
(F1).

- `short_id`: `T-<n>`, from an atomic per-organization counter (F2). Stable
  and quotable in chat.
- `agent_id`, `agent_version`, `prompt_version`: pinned at creation. The
  harness runs the pinned versions; editing the agent does not change a
  task that already exists.
- `project_id`: optional primary project (F13).
- `origin`: set at creation and immutable (CC9). One of:
  - `human`, with the user id;
  - `schedule`, with the scheduler task id;
  - `webhook`, with the webhook id and the delivery id;
  - `task`, with the parent task id and its agent (delegation).
- `owner_id`: the person accountable for the task (F9). Reassignable.
- `budget`: the hard per-task budget in USD. Defaults to the agent's new
  `AgentSettings.task_budget`. May be lowered at creation.
- `status`, `control`, `phase`, `outcome`, `outcome_reason`: see below.
- `cost_total`, `tokens_in`, `tokens_out`, `cache_read_tokens`,
  `cache_write_tokens`: running totals from the ledger.

**`TaskSession`** is one period in which a harness works the task. A task
has many (F1). A session is a tracking record. It is not an execution lease;
leases belong to the harness.

**`TaskEvent`** is one entry in the task's append-only log (F10). Each has
a per-task `seq` (gapless, assigned in the write transaction) and a stable
`event_id` (UUID). The envelope:

| Field | Meaning |
|---|---|
| `event_id` | Stable id; ClickHouse deduplicates on it |
| `seq` | Per-task order |
| `type` | One of the types below |
| `schema_version` | Version of the payload schema for this type |
| `actor_kind` | `human`, `agent`, `subagent`, `system` |
| `actor_id` | User, agent, or service id |
| `channel` | `web`, `slack`, `mcp`, `api`, `harness` (H3) |
| `session_id` | Set when the event comes from a harness session |
| `at` | Time the event happened |
| `payload` | Type-specific JSON, redacted (CC8) |

Standard types:

| Type | Written by | Payload |
|---|---|---|
| `task.created` | Imbi | Title, description, origin, budget, pinned versions |
| `state.changed` | Imbi | From, to, reason |
| `control.changed` | Imbi | From, to, actor |
| `owner.changed` | Imbi | From, to |
| `session.opened` / `session.closed` | Imbi | Session id, harness instance, close reason |
| `turn` | Imbi or harness | Message body; `decision` text when the turn asks for one |
| `tool.called` | Harness | Tool id, mutating flag, arguments, result summary, duration, result, parent call id for nested subagent calls (N3) |
| `phase.changed` | Harness | Phase name, furthest milestone (A3, CC5) |
| `todos.updated` | Harness | The full todo list (F12) |
| `check.reported` | Harness | Name, value, delta, baseline, verdict, source (J2) |
| `usage.reported` | Imbi | Model, token counts, cost, remaining budget |
| `request.opened` / `request.resolved` / `request.expired` | Imbi | Request id and content, resolution |
| `outcome.set` | Imbi | Outcome, reason |

A new type, or an incompatible payload change, raises `schema_version`.
Readers ignore types they do not know.

**`TaskRequest`** asks a person for something (I1).

- `kind`: `feedback` (a decision, with optional options) or `approval` (a
  permitted effect).
- `title`, `why`, `options`, `artifacts`: the content the person decides
  on (I7).
- `artifact_digests`: for `approval`, the digests the approval binds to
  (I3). A request with changed digests is a new request; the old one is
  void.
- `expires_at`: expiry is a terminal outcome (I5).
- Resolution: actor, time, choice or decision, constraints, the digests
  approved (I9). A request resolved by one person collapses for everyone
  else, naming who resolved it (I4).

### States and outcomes

`status` is one of `queued`, `running`, `blocked`, `paused`, or `closed`
(F4).

- `queued` to `running`: a harness opens a session.
- `running` to `blocked`: a request opens. Back to `running` when every open
  request is resolved and the harness opens a session.
- `running` to `paused` and back: the `control` value changes (below).
- Any status to `closed`: an outcome is set. `closed` is final. A
  non-terminal report never overwrites it (CC5).

`outcome` is set only with `closed`, from the closed F5 set:
`done_acted`, `done_nothing_to_act_on`, `no_reason_to_run`,
`partial_capped`, `suppressed_duplicate`, `superseded`,
`cancelled_by_human`, `interrupted_by_operator`, `failed_at_gate`,
`failed_external`, `unmapped_subject`, `exceeded_ceiling`,
`unhandled_no_actor`, `request_expired`, `refused_rate_ceiling`. Every
outcome except `done_acted` carries `outcome_reason` from a closed set per
outcome (F6).

`control` is one of `run`, `pause`, or `cancel`. People set it. It is task
state, not a transcript entry, and each change writes a `control.changed`
event. The harness reads it and acts at its next turn boundary. A harness
that sees `cancel` closes the task with `cancelled_by_human` or
`interrupted_by_operator`.

### The harness reads by polling

The harness learns of human input and control changes by reading events
with `seq` greater than the last one it saw. The session heartbeat returns
the current `control`, the latest `seq`, and the remaining budget, so one
call tells the harness whether anything changed. A push channel may come
later as an optimization. Correctness never depends on it.

### Imbi computes cost; the harness reports tokens

The harness reports, per model call: model id, input tokens, output tokens,
cache read tokens, cache write tokens, and an idempotency key. Imbi:

1. prices the report from the `AIModel` catalog, which gains
   `cache_read_cost_per_million` and `cache_write_cost_per_million`;
2. writes a `budget_ledger` row with the rates used and updates the task
   totals in the same transaction;
3. returns the remaining budget;
4. closes the task with `exceeded_ceiling` when the total passes the budget.

A report with no usable token counts is recorded as unmeasured, not as zero
(N2). A correction is a new ledger row; rows never change.

The budget is checked between model calls. One call can overshoot the
budget by that call's own cost. This bound is accepted for v1. Reserve and
commit operations come only if an overshoot causes a real problem.

`AgentSettings.monthly_cost_cap` stays advisory. The Usage and agent pages
warn at 80% and 100% of it.

### Each agent is its own service principal

Each agent gets a `ServiceAccount`, created and removed with the agent,
`MEMBER_OF` the agent's organization, and linked to the agent by an
`ACTS_AS` edge. The harness authenticates as that service account with the
existing client-credentials flow. Harness-facing endpoints accept a call only
from the service account of the task's agent.

The person who started a task is its origin. The agent never acts with that
person's token (CC9). The service account gets no
`integration:act-as-service` grant (ADR 0017) by default. Which tool
authority an agent receives is a later decision.

### Idempotency

Task creation and usage reports take an idempotency key. The key is unique
per organization, origin kind, origin principal, and key. A repeat returns
the first result. A different principal that sends the same key gets its own
result, never the result of another principal.

### Payloads

Inline payloads are redacted (CC8) and capped in size. A larger payload or
an artifact goes to object storage (the existing upload storage, ADR 0005)
under its digest. The event keeps the digest, size, media type, and a
redacted preview.

### Permissions

| Permission | Allows |
|---|---|
| `agent_task:read` | List and read tasks and their events |
| `agent_task:create` | Create a task manually |
| `agent_task:manage` | Pause, resume, cancel, reassign |
| `agent_task:resolve` | Answer feedback requests and resolve approvals |

An agent's service account cannot resolve a request on its own task or on a
task its subagent works (I6). Approval authority scoped to the project an
effect targets (M2) comes with the tool gating decision.

### Operations Log

Resolutions and terminal outcomes appear in the Operations Log as a
projection of task events (I9, N9). The Operations Log is not a second place
to write them.

### Task relations and associated projects

Added 2026-10-09.

A task can depend on other tasks and can touch projects other than its
primary project (F13). Two tables hold this state:

| Table | Holds |
|---|---|
| `task_dependencies` | One row per dependency: `organization_id`, `dependent_task_id`, `prerequisite_task_id`, `created_by_kind`, `created_by`, `created_at` |
| `task_projects` | One row per associated project: `organization_id`, `task_id`, `project_id`, `project_slug`, `added_by_kind`, `added_by`, `added_at` |

- **One relation, read in two directions.** "A requires B" and "B blocks
  A" are the same row. The UI shows requires and required by, and blocks
  and blocked by, from it.
- **Parent and child are not stored here.** They come from a `task`
  origin, which is immutable. The UI shows them read only, as delegation.
- **Organization isolation is in the keys.** `tasks` has a unique key on
  `(organization_id, id)`. Both tables refer to tasks through
  `(organization_id, task id)` foreign keys, so a row can never join
  tasks in two organizations. The organization comes from the route,
  never from the request body. Application code checks that a project
  belongs to the organization, because projects are in the graph.
- **No self dependency.** A check constraint refuses it. Longer cycles
  are allowed in v1, because a dependency does not gate anything.
- **Dependencies are information only.** A dependency does not change a
  task's status and does not affect dispatch. Before a dependency gates
  anything, cycle checks must come first.
- **The primary project is not in `task_projects`.** Associating the
  primary project is refused. A row stays when its project is deleted
  from the graph; the UI shows the slug snapshot as no longer available.
- **Events.** Each change writes an event: `dependency.added`,
  `dependency.removed`, `project.associated`, `project.dissociated`. A
  dependency event is written on both tasks, in one transaction, with
  the same `operation_id`, both task ids, and the side of each task. The
  transaction locks both tasks in task id order. A removal event keeps
  the full row that was removed. An add that finds the row already there,
  or a remove that finds no row, writes no event.
- **Archived tasks are sealed.** A task whose log is archived gets no new
  events. A dependency between an archived task and a live task writes
  its event only on the live task, and the payload names both tasks. A
  change where every task involved is archived is refused.
- **Who can change them.** People with `agent_task:manage`. The audit
  fields hold an actor kind and id, not a user only, so a later decision
  can let an agent add them through a narrower permission. Agents get no
  write access to relations now.

### Not decided here

- How a harness learns that a task was created (dispatch).
- Which tools agents get, and how a call to a mutating tool is gated.
- Escalation of unanswered requests.
- Joining a new trigger to an existing task on the same subject (F1, Q1).
  Until subject signatures (CC3) exist, triggers pass an explicit
  idempotency key.

## Consequences

- Task history has two homes over time: Postgres until archive, ClickHouse
  after. The events endpoint hides this, but anything that queries storage
  directly must know it.
- Postgres stays small. Only live and recently closed tasks keep events
  there.
- A ClickHouse outage delays archive and the Usage page. It does not stop
  agents, budgets, or the live task view.
- `agent_task_events` has no TTL. It grows with agent activity. A retention
  decision is needed before volume makes it expensive. When one is made, the
  TTL must be on a column every row shares, with no `DELETE WHERE`, so
  ReplacingMergeTree deduplication cannot bring back a removed row.
- Adding both streams means updating `TOPICS`, `clickhouse/schemata.toml`,
  and `compose.ci.yaml` `IGGY_TOPICS`, and restarting `iggy-connect` in each
  environment after the first deploy.
- A harness must poll. Latency for a human reply is the harness's polling
  interval at worst.
- An agent definition now owns a service account. Deleting an agent removes
  it; the task records keep the agent and service account ids for audit.
- `AgentSettings` gains `task_budget`. `AIModel` gains two cache price
  fields. Both need API, UI, and OpenAPI type updates.
