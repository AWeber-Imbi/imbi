# ADR 0028: Tasks Become Tickets

Date: 2026-11-16

## Status

Proposed

This ADR renames agent tasks to **tickets**, as in Jira, and lets a ticket
be assigned to an agent or a person. The Context section uses the current
name, agent task. Every later section uses ticket.

This ADR is an alternative to [ADR 0024](0024-work-items.md) and
[ADR 0025](0025-tickets.md). Accept one of the three.

Related: [ADR 0020](0020-agent-task-contract.md) (agent tasks, extended
and renamed here; `closed` is no longer final), [ADR 0021](0021-workflow-contract.md) (workflows, not
changed), [ADR 0022](0022-agent-harness-and-secrets-broker.md) (harness: a
new session reads the ticket history).

## Context

ADR 0024 and ADR 0025 each add a new record beside agent tasks. Agent
tasks already have most of what that record needs:

- An accountable person (`owner`).
- Questions to people (`requests`), with a `blocked` status while one is
  open.
- An event log, projects (`task_projects`), and dependencies
  (`task_dependencies`).
- Workflow runs that start when a task closes (`task_completed` triggers).

Agent tasks lack three things:

1. A task cannot be assigned to a person. `agent_id`, `agent_version`, and
   `service_account_id` are required.
2. A task has no parent. `chain_id` groups tasks for one runner
   (ADR 0022), so it cannot group work.
3. A dependency is information only. It cannot hold a task until another
   task closes.

The name is also wrong for the job. Teams track work in Jira as tickets,
and a ticket moves between people. Once a task can be assigned to a person
and handed off, it works like a Jira ticket, and it should have that name.

## Decision

Rename agent tasks to tickets. Extend tickets so that a ticket is assigned
to an agent or to a person, and can hand off between them. Add no new
entity.

### Name

A ticket is one piece of work with an owner and an assignee. It moves
between assignees until it closes, as a Jira ticket does.

- Short ids stay `T-<n>`. Existing ids stay valid.
- Public names change:

| Now                                                            | After                                                           |
| -------------------------------------------------------------- | --------------------------------------------------------------- |
| Agent task                                                     | Ticket                                                          |
| `/{org_slug}/agent-tasks`                                      | `/{org_slug}/tickets`                                           |
| `agent_task:read`, `:create`, `:manage`, `:resolve`, `:delete` | `ticket:read`, `:create`, `:manage`, `:resolve`, `:delete`      |
| MCP tools named for agent tasks                                | MCP tools named for tickets (they follow the API operation ids) |
| Workflow trigger `task_completed`                              | `ticket_closed`                                                 |
| Python package `imbi.api.agent_tasks`                          | `imbi.api.tickets`                                              |

- Storage names change:

| Now                                                                                                 | After                                                                   |
| --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Schema `agent_runtime`                                                                              | `tickets`                                                               |
| `tasks`                                                                                             | `tickets`                                                               |
| `task_id_sequences`                                                                                 | `ticket_id_sequences`                                                   |
| `task_dependencies` (`dependent_task_id`, `prerequisite_task_id`)                                   | `ticket_dependencies` (`dependent_ticket_id`, `prerequisite_ticket_id`) |
| `task_projects`                                                                                     | `ticket_projects`                                                       |
| `task_id` in `sessions`, `events`, `requests`, `budget_ledger`, `trigger_outbox`, `ticket_projects` | `ticket_id`                                                             |
| Index names that start with `tasks_`                                                                | `tickets_`                                                              |
| `harness.chains.root_task_id`                                                                       | `root_ticket_id`                                                        |
| `harness.claims.task_id`                                                                            | `ticket_id`                                                             |
| ClickHouse table and Iggy stream `agent_task_events`                                                | `ticket_events`                                                         |
| Iggy topic `agent_tasks`                                                                            | `tickets`                                                               |
| Origin kind `task`                                                                                  | `ticket`                                                                |
| Event type `task.created`                                                                           | `ticket.created`                                                        |

- `agent_usage` keeps its name. It records the usage of agents.

### Rollout

The rename ships without downtime under a rolling deploy. Old and new
names work side by side until no pod uses the old ones, then the old ones
go:

- Postgres tables move to the `tickets` schema, with views under the old
  names. `harness` columns are mirrored by a trigger.
- Events go to `ticket_events`, and readers read both ClickHouse tables
  until the old one is copied and dropped.
- Code reads old and new stored values, then writes the new ones, then
  rewrites stored origin kinds. Logged events keep their type.
- The old API path, `agent_task:*` grants, and the `task_completed`
  trigger keep working through the transition. Saved `task_completed`
  triggers keep working after it.
- Person tickets and handoffs turn on after the old names are gone.

### Assignee

- `assignee_kind`: `agent` or `person`. Default `agent`. It changes only
  through a handoff.
- `assignee`: the email of the person on a person ticket.
- `agent_id`, `agent_version`, and `service_account_id` become nullable. A
  check requires them on agent tickets and forbids them on person tickets.
- `owner` keeps its meaning: the accountable person. On a person ticket,
  the owner and the assignee can differ.

### Statuses by assignee kind

Agent tickets keep the ADR 0020 statuses. Person tickets get `open` and
`in_progress`. Both kinds share `blocked` and `closed`, and gain `held`.
[Reference](#reference) lists every status.

A check ties each status to its assignee kinds. A handoff changes the kind
and the status in one write, so the check holds on every row.

Agent transitions do not change. The claim query reads only `queued`
tickets with a matching `agent_id`, so person tickets and held tickets are
never claimed. One claim rule changes for [Reopen](#reopen).

Person transitions: `open` to `in_progress` to `closed`, `open` or
`in_progress` to `blocked` and back, and `held` to `open`. The assignee
and holders of `ticket:manage` make them. A person ticket closes with an
ADR 0020 outcome: `done_acted`, `done_nothing_to_act_on`, `superseded`, or
`cancelled_by_human`. `control` does not apply to person tickets.

### Handoff

A ticket can pass between an agent and a person, in either direction. It
keeps its id, log, owner, parent, and dependencies.

- A handoff is refused while a session is open or the chain of the ticket
  is pinned (`running`, `fencing`, or `stuck`). To take a running ticket,
  pause it and hand it off when the session closes.
- The status maps in the same write:

| From                    | To a person | To an agent |
| ----------------------- | ----------- | ----------- |
| `queued` or `paused`    | `open`      |             |
| `open` or `in_progress` |             | `queued`    |
| `blocked`               | `open`      | `queued`    |
| `held`                  | `held`      | `held`      |

- Open requests on the ticket close with a new request status, `withdrawn`
  (see [Reference](#reference)).
- A handoff to an agent sets `agent_id`, pins `agent_version`, and sets
  `service_account_id`. A handoff to a person clears them.
- The owner, the assignee, and holders of `ticket:manage` can hand a
  ticket off. An agent hands its own ticket to a person with a new MCP
  tool, `hand_off`, which ends its session.
- The budget counts agent cost across every agent period of the ticket.
  Person time is not metered.

### Reopen

A closed ticket can be reopened, as in Jira.

- Reopening clears `outcome`, `outcome_reason`, and `closed_at`. The
  `reopened` event records the old outcome and a reason.
- The ticket keeps its assignee by default. The person who reopens it can
  name a new assignee of either kind in the same write, as in a handoff.
- A person ticket returns to `open`. An agent ticket returns to `queued`
  and starts a new session, which reads the ticket history.
- A reopened agent ticket starts a new chain. Its `chain_id` becomes its
  own id. If it was already a chain root, its chain row returns to
  `queued` with a new attempt. The claim query finds a root by
  `COALESCE(chain_id, id) = id`, not by origin kind, so a reopened child
  can be claimed. Child tickets made before `chain_id` existed get it from
  their origin ticket, so the rule does not read them as roots.
- Reopening is refused while the chain of the ticket is pinned. A chain
  never changes while a runner holds it.
- Reopening does not change dependents that a gating dependency already
  released, or the parent and children of the ticket.
- The owner, the assignee, and holders of `ticket:manage` can reopen a
  ticket.

The log of a closed ticket may be archived. On reopen, `log_archived_at`
clears, and a new column, `archived_seq`, records the last seq that only
ClickHouse holds. New events go to Postgres with the next seq. A log read
takes events up to `archived_seq` from ClickHouse and the rest from
Postgres. When the ticket closes again, the archive sweep works as
before.

### Ticket history in a new session

A new session starts from the ticket description and reads events only
after `last_seq`. An agent that receives a ticket in a handoff must see
what happened before. The harness gives a new session the ticket history:
the description, comments, resolved requests, handoffs, and the outcomes
of child and prerequisite tickets. This is the one harness change.

### Parent

- `parent_id`: nullable, in the same organization. It is separate from
  `chain_id`. A ticket that an agent creates from its own ticket starts
  with `parent_id` set to that ticket.
- A root ticket and its descendants are one piece of work. The owner of
  the root is accountable for it. The state of the tree is computed on
  read.
- More work on a closed ticket either reopens it or is a new child
  ticket.

A ticket can be reparented, as in Jira:

- Set `parent_id` to another ticket to move the ticket and its descendants
  under it. Clear it to make the ticket a root.
- A move that makes a ticket its own ancestor is refused. imbi-api walks
  the ancestors of the new parent under a per-organization advisory lock,
  so two moves at once cannot make a cycle.
- Open and closed tickets can move. A move changes no status, assignee,
  dependency, or chain.
- The owner of the ticket and holders of `ticket:manage` can move it.

### Gating dependencies

- `ticket_dependencies` gains `gates`, default `false`. Existing rows keep
  their meaning.
- A ticket created with an open gating prerequisite starts `held`. Adding
  a gating dependency moves a ticket that has not started to `held`. A
  started ticket refuses it.
- When the last gating prerequisite closes with `done_acted` or
  `done_nothing_to_act_on`, the dependent moves to `queued` (agent) or
  `open` (person) in the same transaction.
- When a gating prerequisite closes with another outcome, the dependent
  stays `held`. Its owner cancels it, removes the dependency, or adds a new
  prerequisite.

### Waiting on me

A person's list holds:

- Open requests on tickets they own.
- Person tickets assigned to them that are not closed.
- Held tickets they own whose gating prerequisite failed.

### Permissions

`ticket:create` creates either kind. Agent grants apply only to agent
tickets. The assignee of a person ticket can change its status and close
it without `ticket:manage`.

### Events

New types: `reopened` (with the old outcome and a reason),
`assignee.changed` (a person to another person),
`parent.changed` (with the old and new parent), `handed_off`
(a change of kind, with both sides), and `request.withdrawn` (each request
that a handoff closes). Status changes use `status.changed` with new
reasons, such as `prerequisites_done` and `started`.

## Consequences

**Positive**

- One record, one id space (`T-<n>`), one log, and one list for agent and
  person work.
- The name matches how teams already talk about work in Jira.
- No new entity. Existing tables gain columns.
- Escalation, rework, and reopened work stay on one ticket: an agent
  hands off to a person, a person hands back, and a closed ticket
  reopens.
- ADR 0021 does not change. The harness gains one change: it reads the
  ticket history on a new session.
- Work that only people do is covered.
- What moves work forward stays a separate decision.

**Negative**

- The meaning of a status depends on the assignee kind. Sessions,
  heartbeats, timeouts, and budgets do not apply to person tickets, and
  the store must skip them explicitly.
- No single record names a piece of work. Its state is the tree under a
  root, and lists and reports must compute it.
- The rollout spans several releases, and person tickets wait for its
  end. It needs a connector change and an `iggy-connect` restart per
  environment.
- About 30 files in the API, MCP server, and UI read `agent_id`. Each must
  handle a person ticket.
- The rename touches the UI (about 34 files), the API paths, the MCP tool
  names that clients call, role grants, and workflow triggers. MCP clients
  must update before the old names go.
- ADR 0025 also uses the name ticket, with `TK-<n>` ids and a `tickets`
  schema. Accepting this ADR means rejecting ADR 0025, so the two meanings
  never both apply.
- An agent still cannot wait days on a request. The harness waits inside
  the pod, and transcripts stay in the pod. For a long wait, the agent
  hands the ticket to the person instead of opening a request.
- The history that a new session reads grows with the ticket, so it needs
  a size limit.
- `closed` is no longer final, which changes ADR 0020. Code that treats a
  closed ticket as fixed, such as the archive sweep, the `task_completed`
  trigger outbox, and dashboards, must expect a ticket to close more than
  once. A workflow on `ticket_closed` can fire again for the same ticket.
- A log read of a reopened ticket reads two stores.

## Not Decided Here

- What creates the next ticket in a piece of work: a workflow on ticket
  close, a manager agent as in ADR 0025, or a person.
- Stages on a root ticket.
- Jira sync.
- Resuming an agent ticket in a new session.

## Reference

### Ticket statuses

| Status        | Agent | Person | New | Meaning                                                               |
| ------------- | ----- | ------ | --- | --------------------------------------------------------------------- |
| `held`        | yes   | yes    | yes | A gating prerequisite is open. Not claimable                          |
| `queued`      | yes   |        |     | Waiting for a runner                                                  |
| `running`     | yes   |        |     | A session is open                                                     |
| `paused`      | yes   |        |     | `control` is `pause` and no session is open                           |
| `open`        |       | yes    | yes | Assigned to a person, not started                                     |
| `in_progress` |       | yes    | yes | The assignee started work                                             |
| `blocked`     | yes   | yes    |     | Agent: a request is open. Person: waiting on something, with a reason |
| `closed`      | yes   | yes    |     | Ended. `outcome` says how. Can reopen                                 |

### Request statuses

A request is a question that an agent puts to a person during a ticket
(ADR 0020). A `feedback` request needs an answer. An `approval` request
needs a yes or no before the agent acts. While a request is open, its
ticket is `blocked`.

| Status      | Kind       | New | Meaning                             |
| ----------- | ---------- | --- | ----------------------------------- |
| `open`      | both       |     | Waiting on a person                 |
| `answered`  | `feedback` |     | A person answered                   |
| `approved`  | `approval` |     | A person approved                   |
| `rejected`  | `approval` |     | A person rejected                   |
| `withdrawn` | both       | yes | Closed by a handoff, with no answer |

An expired request is not a stored status. Its status stays `open` and its
`expires_at` is past. Imbi no longer counts it as open, and it cannot be
resolved.
