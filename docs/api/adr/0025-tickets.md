# ADR 0025: Tickets

Date: 2026-11-12

## Status

Proposed

This ADR is an alternative to [ADR 0024](0024-work-items.md). Both solve
the same problem. Accept one of them, not both.

Related: [ADR 0020](0020-agent-task-contract.md) (agent tasks),
[ADR 0021](0021-workflow-contract.md) (workflows, not changed here),
[ADR 0022](0022-agent-harness-and-secrets-broker.md) (harness),
[ADR 0023](0023-realtime-channel.md) (realtime channel).

## Context

Software work is tracked in Jira today. The goal is to track it in Imbi
and to have agents carry each piece of work from report to verified
change with no person starting each step.

The scope is set by four decisions:

- **Agents work every ticket.** Imbi does not track work that only
  people do. People report work, answer questions, review, and approve.
- **Work starts on its own.** Creating a ticket starts analysis, and
  analysis leads to implementation with no go from a person. If many
  tickets start at once and runners run short, that is a runner capacity
  problem and is fixed there.
- **Jira is not synced.** Jira keeps running beside Imbi until the move
  is done. A ticket in Imbi exists only in Imbi.
- **Judgment first, proof later.** An agent decides when a ticket is
  verified. The design must let a later decision require proof.

Five facts about the current code shape the decision:

1. **An agent task is one bounded run of one agent.** It needs an agent,
   a budget, and a service account. `closed` is final (ADR 0020). Retry
   creates a new task that is not linked to the old one, so a finished
   task that needs a little more work has nowhere to put it.
2. **A task that waits holds a runner pod.** A blocked chain keeps its
   pod until the request is resolved (ADR 0022). A wait of days for a
   review or a deploy cannot live inside a task.
3. **Nothing wakes an existing task.** A webhook, a schedule, or a
   workflow step can only create a new task. Joining a new trigger to an
   existing task is not decided (ADR 0020).
4. **A workflow run cannot hold a ticket.** A run is an acyclic graph
   that runs once. No step waits for an outside event or for a person,
   and a closed run is final (ADR 0021). ADR 0024 amends all of these.
5. **Imbi already knows pull requests and deploys.** The `pr-sync`
   capability records pull requests, and deployments are recorded per
   project and environment.

## Decision

### Three parts

- A **ticket** is the record of one piece of work. It lasts from the
  report until the change is verified, and it can reopen.
- A **manager** is an agent that moves the ticket forward. It runs for a
  short time whenever something happens on the ticket.
- **Agent tasks** do the work: analysis, implementation, review, and
  verification. ADR 0020 tasks do not change apart from one link.

The ticket carries the continuity, so nothing else has to. Tasks stay
short and final, no workflow run has to last for weeks, and the manager
keeps no state of its own.

### Name

The entity is a **ticket**, short id `TK-<n>`. `T-<n>` is taken by agent
tasks.

### Storage

A new Postgres schema, `tickets`, managed with the same tooling as
`agent_runtime`:

| Table | Holds |
|---|---|
| `tickets` | One row per ticket: identity, fields, status, stage, owner, origin, ceilings, `last_seq` |
| `events` | The append-only log of each ticket |
| `asks` | One row per question put to a person, and its answer |
| `ticket_projects` | One row per ticket and project, with what added it |
| `pull_request_links` | One row per pull request linked to a ticket, with how it was matched |
| `id_sequences` | One counter per organization for short ids |

Rows refer to graph nodes (organization, project, user, agent) by id.
Application code validates those ids on write.

A state change and the event that records it commit in one transaction,
as in ADR 0020. Every event is published through Iggy to the ClickHouse
table `ticket_events` after its transaction commits. Events stay in
Postgres, because a ticket can reopen. There is no archive sweep in v1.

### The ticket

- `short_id`: `TK-<n>`, from an atomic per-organization counter.
- `title`, `description`, `labels`, `priority`, `links`. All editable.
  `priority` is one of `highest`, `high`, `medium`, `low`, `lowest`, or
  unset. `links` holds URLs, such as the Jira issue a ticket came from.
- `status` and `stage`: see States and stages.
- `owner_id`: the person accountable for the ticket. Never empty.
  Defaults to the creator.
- `reporter_id`: the person the work is for.
- `manager_agent_id`: the agent that manages the ticket. Defaults to the
  organization's manager agent.
- Projects: any number, in `ticket_projects`, with no primary. A ticket
  can start with none. Analysis names them, and linking a pull request
  adds its project.
- `origin`: how the ticket was created. Set at creation and immutable.
  One of `human` (with the channel), `webhook`, `schedule`, or `task`
  (an agent created it).
- `budget` and `max_tasks`: see Guardrails.
- `closed_at`, `closed_by`.

### Events

Ticket events use the envelope of ADR 0020's `TaskEvent` without
`session_id`. Standard types:

| Type | Payload |
|---|---|
| `ticket.created` | Title, description, origin, owner |
| `field.changed` | Field, from, to. One event per field |
| `status.changed` | From, to, reason |
| `stage.changed` | From, to, reason |
| `comment.added` | Body, author |
| `project.added` / `project.removed` | Project, source, reason |
| `pull_request.linked` / `pull_request.unlinked` | Repository, number, how it was matched |
| `pull_request.changed` | Repository, number, what changed: opened, checks, review, merged, closed |
| `deploy.reached` | Environment, project, the deploy |
| `released` | Project, version, the release tag |
| `task.started` | Task short id, agent, who started it |
| `task.closed` | Task short id, agent, outcome, the task's result summary |
| `ask.opened` / `ask.answered` / `ask.cancelled` | Ask id, holder, question, answer |
| `ceiling.reached` | Which ceiling, the value |
| `timer.fired` | Why |

Readers ignore types they do not know.

### States and stages

`status` is one of `open`, `in_progress`, `done`, or `cancelled`. It
means the same thing on every ticket, so lists and reports can use it.

`stage` says where an open ticket is. The list is fixed and ordered in
v1:

| Stage | What happens | Leaves when |
|---|---|---|
| Analysis | An analysis task checks that the ticket has what an implementer needs and names the projects. The manager asks the reporter about gaps | The ticket is specified and has projects |
| Implementation | One implement task per project opens pull requests. A failed check starts another implement task | Every linked pull request is open with passing checks |
| Review | A review task, a person, or both review the pull requests. Requested changes start another implement task | Every linked pull request is merged |
| Release | The ticket waits for the merge commits to be deployed, or for a release tag on a library | The change is live where it will be verified |
| Verification | A verify task checks the change where it is live | The verify task reports that the change works |

- The manager sets the stage. It can move a ticket backward, for example
  from Verification to Implementation when the fix does not hold. Each
  change writes `stage.changed` with a reason.
- Status follows stage. A ticket in Analysis is `open`. A ticket in any
  later stage is `in_progress`. `done` and `cancelled` are set by
  closing the ticket.
- Merge has no stage of its own. A pull request merges once it is
  approved and its checks pass, so Review ends at the merge.
- Waiting on a person is an open ask, not a stage. A ticket in Review
  with an open ask is still in Review.
- **Reopen.** A person or the manager can reopen a `done` or `cancelled`
  ticket. Reopening writes `status.changed` with a reason, clears
  `closed_at`, and wakes the manager. The manager reads the log and
  picks the stage. A ticket that needs a small change goes straight to
  Implementation.

### The manager

The manager is an ordinary agent (ADR 0020), with versions, a budget
per task, and a service account. The organization names one agent as its
manager. A ticket can name another, so different kinds of work can have
different managers.

**The manager runs when something happens.** After a ticket event
commits, imbi-api creates a manager task for the ticket when all of
these hold:

- the event is a wake type: `ticket.created`, `field.changed`,
  `comment.added`, `status.changed`, `task.closed`, `ask.answered`,
  `pull_request.changed`, `deploy.reached`, `released`, or `timer.fired`
- the manager's own task for this ticket did not write the event
- the ticket has no open manager task

When a manager task closes, imbi-api checks for a wake event newer than
the task. If there is one, it creates the next manager task.

**Each run starts from the ticket, not from memory.** A manager task
reads the ticket, its log, its tasks, its asks, and its pull request and
deploy state. It does the next thing and reports an outcome. A missed
event or a second run on the same state does no harm, because the
second run finds nothing to do and closes with `done_nothing_to_act_on`.

**A manager task has no projects and clones nothing.** Work that needs
the code is a task for another agent.

**A failed manager task changes nothing on the ticket.** The ticket page
shows the failure. The next wake event runs the manager again, and a
person can run it by hand.

**A timer covers silence.** A scheduler job writes `timer.fired` on each
open ticket that has had no event, no open task, and no open ask for a
set time. The manager then decides whether anything is stuck.

**Manager tools.** A manager task gets these Imbi tools. Its token
allows them for the ticket in its origin only.

| Tool | Does |
|---|---|
| `get_ticket` | Reads the ticket, its events, tasks, asks, pull requests, and deploy state |
| `update_ticket` | Sets stage, labels, priority, and projects |
| `comment_on_ticket` | Adds a comment |
| `start_ticket_task` | Starts a task for a named agent on named projects, with an instruction and a budget |
| `open_ask` / `cancel_ask` | Puts a question to a person, or withdraws one |
| `close_ticket` | Sets `done` or `cancelled`, with a reason |

The manager agent's settings list the agents it may start. Ticket text
can come from outside the organization, so the manager must not be able
to start an agent that the organization did not choose for ticket work.

### Tasks on a ticket

`agent_runtime.tasks` gains a nullable `ticket_id`. It is set at
creation, or once on a ticketless task (see below), and never changes
after that.

- **A new origin kind, `ticket`.** A task the manager starts has origin
  `ticket`, with the ticket id and the manager task that started it. Its
  owner is the ticket's owner. A manager task has the same origin kind,
  with the ticket event that woke it.
- **A ticket task is the root of its own chain.** A chain is a root task
  and its `task` origin children (ADR 0022). A `ticket` origin is not a
  child, so the manager's pod is not held while the work runs, and tasks
  for several projects run on several runners. A ticket task can still
  delegate with `create_child_task`, and its children copy `ticket_id`.
- **More work is a new task.** A failed check, requested changes, a
  failed verification, and a reopened ticket all lead to the same
  action: the manager starts another task on the ticket. The new task
  gets its context from the ticket log and the pull request. Tasks stay
  final, and ADR 0020 does not change.
- **One log across tasks.** When a ticket task closes, imbi-api writes
  `task.closed` on the ticket with the outcome and the task's result
  summary. Each task's own log stays the full record of that task.
- **Worker tools.** A ticket task gets `get_ticket` and
  `comment_on_ticket` for its ticket, and its prompt gets the ticket's
  short id.
- **A person can start a task on a ticket** from the ticket page. The
  task records the ticket and keeps its `human` origin.
- **Tasks without a ticket are unchanged.** A scheduled job, a webhook
  task, a workflow step, and a task someone runs by hand have no ticket.
- **Follow up.** A closed task with no ticket gains a Follow up action.
  It creates a ticket from the task's title and description, links the
  closed task to it, and starts the manager. This replaces the unlinked
  retry for work that succeeded and then needed more.

ADR 0024 cites requirements F17 and I8: an agent's rework stays in its
task, woken by review comments and check results. This ADR does not
build that. If waking a task is built later, the manager can reply to an
open task instead of starting a new one.

### Asks

An ask is one question put to one person about a ticket. The manager
cannot use an ADR 0020 request for this, because a blocked task holds a
pod. The manager opens an ask and its task ends. The answer wakes it.

- An ask has a holder, a question, optional choices, optional links, and
  a due date. To ask several people, the manager opens several asks.
- The manager chooses the holder from the people `get_ticket` returns:
  the owner, the reporter, the requested reviewers of linked pull
  requests, and the owners of the ticket's projects.
- The holder or a person with `ticket:write` answers, with a choice or
  with text. Answering writes `ask.answered`.
- A person with `ticket:write` can hand an ask to someone else.
- The manager can cancel an ask that no longer matters, for example a
  review ask whose pull request was approved on GitHub.
- Closing or cancelling a ticket cancels its open asks.

### Waiting on me

**Waiting on me** lists what one person must act on:

- their open asks
- open requests on agent tasks they own (ADR 0020)

Entries sort by ticket priority, then by how long they have waited,
oldest first. The UI, Slack, and the MCP tool `waiting_on_me` all read
this list.

When an ask opens, the slackbot sends its holder a direct message with
the question and a link. A scheduler job sends each person a daily list
of their open asks.

### Pull requests and deploys

- **Linking.** A pull request is linked to a ticket when its title,
  branch, or body contains the ticket's short id. Ticket tasks are told
  to put the short id in the branch name. A person can link or unlink
  one by hand. Linking adds the pull request's project to the ticket.
- **Changes.** When `pr-sync` records a change to a linked pull request,
  imbi-api writes `pull_request.changed` if one of these changed: opened,
  the combined result of its checks, its review state, merged, or
  closed. A single check that finishes while others still run writes
  nothing.
- **Live.** A project is live in an environment when the merge commit of
  every linked pull request in that project is in the project's current
  deploy there. The first time that becomes true, imbi-api writes
  `deploy.reached`. A library has no deploys. It writes `released` when
  a release tag contains those merge commits. This is the rule of ADR
  0024, computed from the same records.
- A pull request closed without merging stays linked and is left out of
  these rules.

### Guardrails

The manager uses judgment. imbi-api enforces the rules that must not
depend on it:

- A ticket has at most one open manager task.
- `close_ticket` with `done` is refused while a linked pull request is
  open or a ticket task is open.
- Cancelling a ticket cancels its open tasks and asks.
- **Ceilings.** A ticket has a `budget` (the total cost of its tasks)
  and a `max_tasks`. Both default from organization settings. Past
  either one, `start_ticket_task` is refused, and imbi-api writes
  `ceiling.reached` and opens an ask for the owner. The owner raises the
  ceiling or cancels the ticket. This stops a manager that keeps
  starting implement tasks against a check that never passes.
- A manager task can act on its own ticket only.

**Proof later.** Verification is a task, and its outcome is on the
ticket log. A later decision can require proof with one more rule:
`done` is refused unless a task of a named verify agent closed with
`done_acted` after the last merge. `check.reported` events (ADR 0020)
can carry the evidence. Neither needs a change to this design.

### Creating tickets

A ticket is created from the UI, the API, the MCP, the slackbot, a
gateway webhook action `create_ticket`, or an agent task. Text that
comes from a webhook is fenced as untrusted, as the gateway does for
`create_agent_task`.

### Permissions

| Permission | Allows |
|---|---|
| `ticket:read` | List and read tickets and their events |
| `ticket:create` | Create a ticket |
| `ticket:write` | Edit, comment, reopen, close, answer or hand over an ask, link pull requests, start a task |
| `ticket:delete` | Delete a ticket |

The member role gets read, create, and write by default.

### Realtime

When ADR 0023 is accepted, ticket writes publish to
`ticket:<org>:<short_id>`, and changes to a person's Waiting on me
publish to `user:<user_id>`.

### Compared with ADR 0024

Both ADRs add a record that is separate from the agent task, with a
coarse status that can reopen, a stage, an event log in the ADR 0020
envelope, a nullable link on tasks, pull request linking by short id,
live computed from deploy records, and one Waiting on me list.

They differ here:

| | ADR 0024 | This ADR |
|---|---|---|
| What moves the work | One workflow run per work item, lasting as long as the work item | A manager agent that runs briefly on each event |
| ADR 0021 | Amended: send-backs, for each, parked steps, no run limit, four step types, workflows with no trigger | Not changed |
| Rework | The same task is woken | A new task on the same ticket |
| Reopen | The workflow starts again from the beginning | The manager reads the log and picks the stage |
| Waiting on a person | Turns, roles, and role resolvers | Asks, with the holder chosen by the manager |
| Work only people do | Supported | Out of scope |
| Jira | Synced through an `issues` capability | Not synced |
| Where the process is defined | A drawn workflow per work item type | The manager agent's prompt |
| New tables | 10 | 6 |

### Not decided here

- Stages that an organization defines. The list is fixed in v1.
- Stages per environment. The manager's prompt says where a change is
  verified. Verifying in testing and again in production needs a
  decision on whether Release and Verification repeat.
- Dispatch by ticket priority. Runners claim the oldest queued task.
- A workflow as the manager. If ADR 0021 gains waits and loops, a ticket
  could name a workflow in place of a manager agent.
- Moving open Jira issues into tickets.
- Quiet hours, digests, and reminders beyond the daily list.
- A retention policy for ticket events.

## Consequences

- The process is in a prompt, not in a drawn graph. It is easy to change
  and can handle cases nobody drew. It is also less predictable: two
  runs of the manager on the same ticket can choose differently. The
  guardrails bound what a wrong choice can do.
- Every wake costs a manager task: a runner pod and a model call. A
  ticket takes many wakes over its life.
- Tickets start work with no limit on how many are in progress. Runner
  pools are the limit. The manager agent must have no low
  `max_concurrent_tasks`, or tickets wait behind it.
- A rework task starts with a fresh workspace and learns what happened
  from the ticket log and the pull request. Tasks on a ticket must leave
  useful result summaries and comments.
- `agent_runtime.tasks` gains a nullable column and a new origin kind.
  Both need migrations that keep the old code working during a rolling
  deploy.
- ADR 0020 and ADR 0022 keep their contracts. ADR 0021 is not touched.
- Writes that add a ticket event also decide whether to wake the
  manager. That check runs inside imbi-api after the write commits.
- Imbi does not write to Jira. While both run, a piece of work is in one
  system or the other, and people must know which.
- Adding the stream means updating `TOPICS`, `clickhouse/schemata.toml`,
  and `compose.ci.yaml` `IGGY_TOPICS`, and restarting `iggy-connect` in
  each environment after the first deploy.
