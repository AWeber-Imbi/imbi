# ADR 0024: Work Items

Date: 2026-11-06

## Status

Proposed

Related: [ADR 0008](0008-plugin-system-architecture.md) (plugins),
[ADR 0020](0020-agent-task-contract.md) (agent tasks),
[ADR 0021](0021-workflow-contract.md) (workflows, amended here),
[ADR 0022](0022-agent-harness-and-secrets-broker.md) (harness),
[ADR 0023](0023-realtime-channel.md) (realtime channel).

Requirement ids such as [F1][req-f-tasks] and [G9][req-g-delegation] refer to
[`docs/agentic-platform-requirements.md`][req] in the
dev-environment repository, as in ADR 0020. The architecture page
[Work Items](../../architecture/work-items.md) shows the parts and flows
this ADR decides.

## Context

Imbi records agent work (ADR 0020) and runs workflows (ADR 0021). It has
no record of the work that people own: a bug to fix, a review to give, a
release to verify, a request someone made in Slack.

That work is tracked today in Jira and in HandoffBee. HandoffBee is a
service outside Imbi that relays Jira and GitHub events. It keeps:

- a per-person board of what is waiting on each person, grouped by stage
  (go/no-go, triage, implement, PR review, merge, testing, acceptance,
  awaiting release, staging, live);
- a turn: the Jira assignee is always the one person who must act next.
  Everyone else in the role is told, but the turn goes to one person;
- role fields on the issue (product owner, review engineers, testers) and
  people it derives from GitHub (PR author, requested reviewers,
  approvers);
- asks from Slack and the web, each with an owner, an asker, and a due
  date;
- personal priorities that only that person sees;
- the WorkerBee handshake, through Jira labels such as
  `workerbee-implement-fix` and `workerbee-fix-implemented`;
- "live" detection, by comparing the merge commits of an item's pull
  requests with the deploys of each environment;
- Slack DMs, quiet hours, a morning list per person, reminders, and a
  weekly digest.

Our goal is to move task management off Jira and into Imbi. Jira keeps
working until that move is done, and external ticketing systems such as
Jira and GitHub Issues come into one interface through plugins.

Five facts shape the decision:

1. **The thing being tracked moves between people and agents.** One bug
   is triaged by an agent, fixed by another, reviewed by a third,
   accepted by a product owner, and verified in production by a fourth.
   It outlives every single step of that work.
2. **A task is one agent on one subject ([F1][req-f-tasks]).** Two agents on the same
   subject are two tasks, related by subject and discoverable from each
   other ([O3][req-o-inbox-and-transcript], [G9][req-g-delegation]). A workflow run creates a new task for each agent step,
   and those tasks are not linked to each other.
3. **An agent's own rework stays in its task ([F17][req-f-tasks], [I8][req-i-human-gates]).** Review
   comments, CI results, and merges wake the same task in a new session,
   with rounds numbered and bounded.
4. **External systems own some of this work during the move.** A Jira
   issue's status, assignee, and labels are changed in Jira by people
   and by WorkerBee. Imbi cannot be the only writer.
5. **Imbi already knows pull requests, commits, and deploys per
   environment.** HandoffBee rebuilds this from GitHub webhooks. Imbi can
   compute it from its own data.

## Decision

### A new entity, not a repurposed agent task

Work items are a new entity. `AgentTask` does not change to carry human
work. The reasons:

- **An agent task belongs to one agent.** It requires an agent, its
  version, a budget, and the agent's service account. A work item is
  worked by several agents and by people, so no single task can stand
  for it.
- **The states describe execution.** `queued`, `running`, `blocked`,
  `paused`, and `closed`, with 15 outcomes such as `exceeded_ceiling` and
  `failed_at_gate`, describe a harness working a task. None of them fits
  "waiting for review" or "merged, not live".
- **The lifetimes differ.** A task runs from the moment it is created
  until its agent reports an outcome, for example from "implement the
  fix" to the pull request merging. Then it closes, and `closed` is
  final. A work item runs from the moment someone reports the work until
  the change is verified in production: triage, implement, review,
  acceptance, merge, each deploy, and verification. It reopens when the
  fix does not hold. Task logs are sealed once archived; a work item
  keeps taking events.
- **One work item spans many tasks.** Fact 2 means a work item worked by
  three agents has three tasks. The work item is the shared subject that
  ties them together. Making it a task would need a task that contains
  tasks, which [F1][req-f-tasks] rules out.
- **The harness contract would move.** ADR 0020 is the contract between
  Imbi and every harness. Changing the task to fit human work changes that
  contract for a need the harness does not have.
- **The permissions differ.** `agent_task:*` grants decide who can start,
  steer, and pay for agents. Work items are for every member of the
  organization.

Agent tasks stay as ADR 0020 defines them. They gain one link to work
items and take their owner from the step that creates them (below).

### Name

The entity is a **work item**, short id `W-<n>`. [F15][req-f-tasks]
says "work items within a task" for the items an agent loops over inside
one task. Those are not platform objects and are not this entity.

### Storage

A new Postgres schema, `work_items`, managed with the same tooling as
`agent_runtime`:

| Table | Holds |
|---|---|
| `work_items` | One row per work item: identity, status, stage, owner, dates, origin, external issue, driving run |
| `turns` | One row per turn: work item, run step, holder (a person or an agent), on behalf of, role, opened and closed times |
| `work_item_projects` | One row per work item and project, with what added it first: an agent task, a pull request link, the external issue, or a person. The pull requests themselves are in `pull_request_links` |
| `role_members` | One row per work item, role, and person set on the item or mapped from an external field |
| `events` | The append-only log of each work item |
| `pull_request_links` | One row per pull request linked to a work item, with how it was matched |
| `notifications` | The outbox of messages to deliver, with their state |
| `notification_settings` | One row per person: channels, quiet hours, morning list, away until |
| `views` | Saved filters, personal or shared, which digests use |
| `id_sequences` | One counter per organization for short ids |

Rows refer to graph nodes (organization, project, user, agent) by id.
Application code validates those ids on write.

A state change and the event that records it commit in one transaction,
as in ADR 0020. Every event is published through Iggy to the ClickHouse
table `work_item_events` after its transaction commits. Events stay in
Postgres. There are far fewer work items than agent tasks, and a work
item can be reopened, so there is no archive sweep in v1.

### Entities

**`WorkItem`** is one piece of work that people and agents move to done.

- `short_id`: `W-<n>`, from an atomic per-organization counter. Stable and
  quotable in chat.
- Projects: any number, in `work_item_projects`, with no primary. A
  work item starts with none. The work finds them (Projects come from
  the work, below).
- `type`: one of the organization's work item types, such as `bug`,
  `story`, or `ask`. The type picks the workflow (Workflows, below).
- `title`, `description`, `labels`, `due_on`, `priority`.
- `status`: see States.
- `stage`: the label of the step the driving run is on, such as
  `PR review`. Set by the engine. Empty on a work item with no
  workflow. For display and filters only.
- `owner_id`: the person accountable for the work item. Never empty.
  For an ask, the person asked. Otherwise it defaults to the creator.
- `reporter_id`: the person the work is for. For an ask, the asker.
- Turns: who must act next, in `turns`. A work item can have several
  open turns (Turns, below). A done or cancelled work item has none.
- `driving_run_id`: the workflow run in charge of the work item. It opens
  turns and sets stage and roles. Empty only on a work item with no
  workflow. See Workflows.
- `origin`: how the work item was created. Set at creation and
  immutable. One of:
    - `human`: a person created it. Holds the user id and the channel
      (`web`, `slack`, `mcp`, `api`).
    - `webhook`: a gateway webhook created it. Holds the webhook id and
      the delivery id.
    - `workflow`: a workflow step created it. Holds the run id and the
      node key.
    - `issue_sync`: the issues plugin created it from an external issue
      it synced. Holds the plugin slug and the issue key.
- `external_issue`: the issue that backs the work item, for as long as
  one does: the plugin slug, the integration id, the issue key, and the
  URL. Unique per organization, plugin, and key. Empty on a native work
  item. A person who links a Jira issue to a work item they created sets
  this, while `origin` stays `human`.
- `closed_at`, `closed_by`.

**Roles.** A role is a named list of people on one work item, such as
`product_owner`, `testers`, or `dba`. A workflow declares any number of
roles, and each role has an ordered list of **resolvers** that decide who
is in it. Imbi tries them in order and uses the first that names
someone:

| Resolver | Who it names |
|---|---|
| Set on the work item | People someone set on the work item page |
| External field | People the issues plugin maps from a field, such as a Jira custom field |
| Plugin | People a plugin returns through a new `role_resolver` capability, such as the PagerDuty on-call for a project |
| Work item | People in the work item's own data: reporter, owner, current or previous turn holders, the actor of the event that started the step, the person who chose the outcome at a named earlier step |
| Pull requests | People on the linked pull requests: authors, requested reviewers, approvers, mergers |
| Named people | Specific people, as a last fallback |

Only members set on the work item or mapped from an external field are
stored, in `role_members`. The other resolvers run when a step reads the
role, because the data behind them changes on its own: a reviewer is
added on GitHub, the on-call rotates, a turn moves. A stored copy would
go stale.

Who picks the work item up next is the workflow's choice. A Turn step
lists roles in order and gives the turn to the first person or to
everyone. When the choice depends on the work item, a Branch step picks
between Turn steps on its fields and facts. A work item with no pull
request, such as "rotate the database credentials", can give the turn to
a `dba` role filled from the database on-call, with named people as its
fallback.

**`WorkItemEvent`** uses the envelope of ADR 0020's `TaskEvent`
(`event_id`, `seq`, `type`, `schema_version`, `actor_kind`, `actor_id`,
`channel`, `at`, `payload`). Standard types:

| Type | Payload |
|---|---|
| `work_item.created` | Title, description, origin, owner |
| `field.changed` | Field, from, to. One event per field |
| `status.changed` | From, to, reason |
| `stage.changed` | From, to, run, node |
| `turn.opened` / `turn.closed` | Holder, role, on behalf of, run, node, reason |
| `role.changed` | Role, added, removed |
| `label.added` / `label.removed` | Label |
| `comment.added` | Body, author. Mirrored comments name their source |
| `outcome.chosen` | Run, node, outcome, actor, channel, how it was read (button, reply, fact) |
| `pull_request.linked` / `pull_request.unlinked` | Repository, number, how it was matched |
| `project.added` / `project.removed` | Project, source (task, pull request, external issue, person), reason |
| `fact.changed` | Fact, from, to |
| `agent_task.started` | Task short id, agent, run, node |
| `agent_task.closed` | Task short id, outcome, the task's result summary, artifact links |
| `run.started` / `run.finished` | Workflow, run id, result |
| `live.reached` | Environment, the deploys that made it live |
| `released` | Project, version, the release tag |
| `external.synced` | The external fields that changed |

Readers ignore types they do not know.

### States

`status` is one of `open`, `in_progress`, `done`, or `cancelled`.

- `open` to `in_progress`: someone starts the work, or a step does.
- `open` or `in_progress` to `done` or `cancelled`: someone closes it,
  or a step does.
- `done` or `cancelled` back to `open`: someone reopens it. Reopening
  writes a `status.changed` event with a reason and clears `closed_at`.
  A work item with a workflow starts a new run of that workflow from the
  beginning.

Status is coarse on purpose. It has to mean the same thing on every work
item, whatever workflow drives it and whatever system backs it, so the
digests, views, and reports can use it. A backed work item maps the
external status category onto it: Jira's To Do, In Progress, and Done,
and GitHub's open and closed.

The detailed state is `stage`. Each workflow step has an optional
**stage label**, such as `Triage`, `PR review`, `Awaiting release`, or
`Live in testing`. When the driving run enters a step with a stage
label, it writes the label to `stage` and logs `stage.changed`. A step
with no label leaves the stage as it is. When parallel branches run,
the stage is the label of the step entered last. An Update work item step can
also set it directly. For example, the Turn "PO acceptance" has the
stage label `Acceptance`, so the work item shows Acceptance while it
waits on the product owner. A workflow gets as
many stages as it has steps, named for that workflow. A work item with
no workflow has no stage.

### Turns

A turn is one person or agent who must act on a waiting step. Each turn
has one holder, and a work item can have several open turns at once:
two reviewers on one Turn step, or an agent implementing on one branch
while a person reviews on another. Each holder sees the work item in
their own Waiting on me.

- A Turn step's **give the turn to** setting is `first` or `everyone`.
  `first` opens one turn for the first person its "turn goes to" list
  resolves to and tells the rest, as HandoffBee does. `everyone` opens a
  turn for each person in the list, so every PR reviewer has it on their
  board.
- With `everyone`, the step's **done when** setting is `any` or `all`.
  `any`: the first outcome chosen finishes the step and closes the other
  turns. `all`: the step waits for every holder, then takes the first
  port in its outcome order that any holder chose. Outcomes are listed
  worst first, so one `Request changes` beats two `Approve`s.
- An agent step opens one turn for the agent, on behalf of the first
  person its "on behalf of" role resolves to. That person is accountable
  for the agent's work.
- When that agent opens a request ([I1][req-i-human-gates]), such as a
  question or an approval, Imbi opens a turn on the work item for the
  person who can resolve it, with the request as the turn's ask.
  Resolving the request closes the turn. The agent's own turn stays
  open.
- A work item a person creates for themself can have no workflow, like
  a to-do. They hold its turn until they close it or start a workflow on
  it. Every other work item has a driving run from the moment it is
  created.
- A person with `work_item:write` can hand one turn to someone else.
  That closes the turn and opens one for the new holder on the same step.
  The step keeps waiting for its outcome.
- A Turn step always opens at least one turn. When its lists resolve to
  nobody, it takes its fallback list, then the owner.
- A step's turns close when the step finishes.
- Nobody is notified of their own action, and an agent's action never
  notifies the agent ([H5][req-h-participation-and-channels]).

### Agent tasks and runs link to the work item

`agent_runtime.tasks` and `workflow_runtime.runs` each gain a nullable
`work_item_id`, set at creation and immutable.

- A run started for a work item records it. Every agent task the run
  creates copies it. A person can start an agent task from a work item
  page; the task records the work item and keeps its `human` origin.
- **The task owner comes from the step ([F9][req-f-tasks]).** A task an
  agent step creates gets the first person of the step's "on behalf of"
  role as its owner. The other members of that role become its watchers.
  When a person starts an agent task by hand from the work item page,
  that person owns it.
  Handing an agent's turn to another person makes them the owner of that
  agent's open task and writes `owner.changed` on it.
- **One log across tasks ([F10][req-f-tasks]).** When a task on a work item closes,
  imbi-api writes `agent_task.closed` to the work item with the task's
  outcome, its result summary, and its artifact links. Agents read the
  work item and its events through the Imbi MCP (`get_work_item`,
  `list_work_item_events`). The agent prompt gets `work_item_short_id`
  as a variable. Each task's transcript stays the full record of that
  task; the work item log is the record across tasks.
- **Rework stays in the task ([F17][req-f-tasks], [I8][req-i-human-gates]).** An agent fixing its own pull
  request is one task, woken by review comments and CI results, with its
  rounds capped by its agent definition. A send-back (below) that
  re-runs an agent step whose task is still open wakes that task. One
  that re-runs an agent step whose task has closed starts a new task.
- **Review is its own task, and runs while the implement task is
  open.** The review agent gets its own task, on its own step. It cannot
  come after the implement step in sequence: an `agent` step waits for
  its task to close, and the implement task stays open until its pull
  request merges, so it can answer review comments ([F17][req-f-tasks]).
  The merge needs the review, so a review placed after Implement would
  wait forever. Instead the flow splits in two before Implement: one
  branch is the implement step; the other is a Gate on `pr.ready`, then
  the review step, then the acceptance Turn. The branches join with
  `all` before the release steps. The two tasks talk through the pull
  request. A reject sends back to the Gate, and the reject comment wakes
  the open implement task. If the implement step takes its `Failed`
  port, the engine cancels the waiting steps on the other branch.
- An agent task with no work item is unchanged.

### One "Waiting on me" list

Imbi's agent task inbox ([O1][req-o-inbox-and-transcript]) becomes
**Waiting on me**. It lists the person's open turns. An agent's request
on a work item is a turn (Turns, above), so it shows the same way.

The only other entries are requests on agent tasks with no work item,
such as a DataFix someone started directly.

Entries sort by priority, then due date, then how long they have waited,
oldest first. [O2][req-o-inbox-and-transcript] sorts by wait alone;
priority and due date come first here. Everything that tells a person
what is waiting on them (the UI, the morning list, Slack reminders, and
the MCP `waiting_on_me` tool) reads this list and nothing else.

Being in a role does not put a work item in a person's Waiting on me;
holding a turn does. This matches HandoffBee, where only the assignee is
on the hook.

Waiting on me is personal. [O1][req-o-inbox-and-transcript] counts
waiting work across the organization; for work items that is a saved
view.

### Workflows drive work items

**Roles are declared on the workflow.** Workflow settings list the roles
the workflow uses. Each has a label, a key, its resolvers in order
(Roles, above), and whether a run can start without it.

**Every work item has a workflow.** Each work item type names a
workflow, and the organization sets a default type. Creating a work item
starts a run of its type's workflow at once and records it in
`driving_run_id`. When a work item is created or reopened, by anyone
or anything, Imbi looks up the workflow its type names and starts it
with that work item. This is not a trigger. ADR 0021 requires every
workflow to begin with one; this ADR amends it so a workflow marked as a
work item workflow has none, and Imbi starts it directly. Only a work
item workflow can be named by a type. Imbi ships no workflows and no types; an organization
sets up at least the default before people can create work items. The
issues plugin maps the external issue type to a work item type
(`type_map`). The one exception is a work item a person creates for
themself with no workflow (Turns, above). They can start a workflow on
it later, and that run becomes its driving run.

**One run per work item.** A work item has one workflow run at a time,
its driving run. It opens turns and sets stage and roles. No other run
acts on the work item. Every path to the end of the workflow must
close the work item as `done` or `cancelled`; the editor refuses one that
does not, so a run never ends while its work item is open. Waiting for
something to happen, such as a Jira label that hands the work to
WorkerBee, is a Gate inside the workflow, not a new run. Reminders and
alerts are settings on Turn steps.

**Long runs.** A driving run can last weeks. Max run time accepts "No
limit" for driving workflows. A step that is waiting holds no lease. The
engine parks it and wakes it on a work item event, a fact change, or a
timer.

**New step types:**

| Type | Does | Ports |
|---|---|---|
| Turn | Opens turns (for the first person or for everyone in its list), tells people, reminds, and waits for an outcome. The outcome comes from a button, a reply read by a model, or a fact turning true. Can write to the external system on enter. Can be skipped by a condition | One per outcome, plus `No answer` |
| Gate | Waits until a condition over facts is true, such as "PR approved and checks green" or "live in testing". Gives no turn | `Met`, `Timed out` |
| Branch | Picks a port from conditions over facts and fields, in order, with no model call ([R1][req-r-deterministic-decisioning-and-routing]). Records which condition matched | One per case, plus `Else` |
| Update work item | Sets status, stage, labels, roles, or fields. Writes through the plugin on a backed item | `Done` |

The `agent` step gains two parameters on runs for a work item:

- **On behalf of**, one of the workflow's roles. The task owner is the
  first person that role resolves to, and the role's members are
  watchers. A request the agent opens ([I1][req-i-human-gates]) becomes
  a turn for that owner (Turns, above).
- **Verdicts**, the named outcomes the agent reports when it closes the
  task, such as `approved` and `rejected` for a review agent. Each
  verdict is a port, beside `Failed`. A verdict the step does not
  declare takes `Failed`.

**Choosing an outcome.** Each holder chooses for their own turn. Anyone
in the step's "turn goes to" list who holds no turn can choose too; a
turn opens for them first, and both writes commit together, so the log
names who acted. There is no extra confirm.

**Away.** A person can mark themselves away until a date. Turn
resolution skips people who are away and takes the next person in the
list, then the fallback list. A turn already held stays held and is
listed for the work item's owner under My roles.

**Asks.** An ask from Slack or the web is a native work item with origin
`human`, channel `slack` or `web`, the asker as reporter, and the person
asked as owner. Its type is the one the organization uses for asks, and
that type's workflow gives the owner the turn and reminds them.

**From Slack.** The slackbot creates a work item three ways:

- **A reaction.** The organization maps emoji to work item types, such
  as `:bug:` to `bug`. Reacting to a message creates a work item of that
  type from the message.
- **A mention.** Mentioning the bot in a message or thread, such as
  "@imbi track this", creates a work item of the default type. Naming a
  type or a person ("@imbi bug for @dana") sets them.
- **A message shortcut.** It opens a form with the message filled in.

The person who reacted or mentioned is the reporter, and the default
owner. The work item's origin is `human` with channel `slack` and the
message's permalink. Its description is the message, and the slackbot
replies in the thread with the work item's link. Later replies in that
thread become `comment.added` events on the work item, and comments on
the work item post back to the thread.

**Facts** are named, typed values about a work item. Imbi computes a
fact when a step reads it, and recomputes it when its data changes if a
parked step watches it:

| Group | Examples |
|---|---|
| Pull requests | `pr.open`, `pr.approved`, `pr.changes_requested`, `pr.checks`, `pr.merged`, `pr.ready` (the readiness judge). Each is true when it holds for every linked pull request not closed without merging; `pr.<repository>#<number>.*` reads one |
| Deploys and releases | `live_in.<environment>`, `live_in.<environment>.<project>`, `deployed_sha.<environment>.<project>`, `released`, `released.<project>`, `released_version.<project>` |
| Checks | `check.<name>.status` for a named CI check or preview |
| Work item | Status, labels, fields, roles |

A change to a fact that a parked step watches writes `fact.changed` and
wakes the step. Facts come from data Imbi already has (pr-sync,
deployments) or from a plugin.

### Projects come from the work

Nobody has to know the projects when they create a work item. The flow
finds them:

1. **Triage names them.** The triage agent reads the work item, finds
   the projects that need a change, and adds each one with the MCP tool
   `add_work_item_project`, giving a reason. Each row records the task
   as its source.
2. **The work fans out.** The Implement agent step runs **for each**
   project on the work item: one task per project, each opening pull
   requests in that project's repository.
3. **Pull requests add the rest.** Linking a pull request adds its
   project if it is not there yet, with the pull request as its source.
   An agent that finds it must change another repository opens a pull
   request there, and its project joins the work item that way.

Other sources:

- The plugin maps external fields to projects, such as a Jira component,
  when the integration declares a mapping.
- A person can add or remove a project by hand. They never have to.

Removal: unlinking the last pull request of a project removes the
project when a pull request link added it. A project that an agent, a
person, or the plugin added stays until an agent or a person removes it,
which writes `project.removed` with the reason.

### For each: amendment to ADR 0021

A step can run **for each** item of a list: `work_item.projects`, or
`work_item.pull_requests`. The engine starts one instance of the step per
item, each with its own step record, idempotency key
(`<run_id>:<node_key>:<round>:<item>`), and, for an agent step, task. The step finishes when
every instance has finished:

- Ports aggregate. The step takes a verdict port only when every
  instance reported that verdict. Any `Failed` instance takes `Failed`.
  A mix of verdicts takes the first port in the step's verdict order,
  which a definition lists worst first (for example `rejected` before
  `approved`).
- The step starts one instance per item in the list. An item added
  before the step finishes starts one more instance.
- A send-back to a for each step re-runs only the instances whose item
  the send-back names, or all of them when it names none.

For example, a workflow can run Implement for each project and Review
for each pull request.

### Send-backs: amendment to ADR 0021

ADR 0021 requires a directed acyclic graph. A work item flow must send
work back: a product owner rejects a change, a verify agent finds the
fix does not hold, a reviewer of the triage asks for more. This ADR amends ADR
0021 as follows:

- The drawn graph stays acyclic. A Turn outcome, a Gate port, or an
  agent step verdict can be marked **send back to** an earlier node on a
  path to it. A send-back is not an edge of the graph.
- Taking a send-back starts a new **round** at the target node. The
  target and every node downstream of it get new step records with the
  round number. Earlier rounds stay in the run history.
- Each send-back has a cap (default 3). The next send-back past the cap
  takes the step's `Too many rounds` port instead, which the workflow
  connects like any other port.
- The idempotency key becomes `<run_id>:<node_key>:<round>`.
- Validation refuses a send-back to a node that is not upstream.

### External issues come in through a plugin capability

A new capability kind, `issues`, joins `CAPABILITY_CONTRACTS`
(`libraries/common/src/imbi/common/plugins/base.py`):

| Operation | Does |
|---|---|
| `get(key)` | Read one issue |
| `search(query)` | Find issues to link |
| `create(fields)` | Create an issue for a new backed work item |
| `update(key, fields)` | Change title, description, assignee, labels, due date, priority, role fields |
| `transition(key, status)` | Move the issue to a status |
| `comment(key, body)` | Add a comment |
| `parse_webhook(payload)` | Turn a webhook delivery into a list of field changes |
| `status_map` | The external statuses and the work item status each maps to |
| `field_map` | The external fields that fill each role |
| `type_map` | The external issue types and the work item type each maps to |
| `priority_map` | The external priorities and the work item priority each maps to |

The first two plugins are Jira (a new `plugins/jira`) and GitHub Issues
(added to `plugins/github`).

For a backed work item, the external system is the source of truth for
`title`, `description`, `status`, `labels`, `due_on`, `priority`, and the
role fields in `field_map`.

- **Reads.** A gateway webhook rule with the new built-in action
  `sync_work_item` passes each delivery to `parse_webhook` and applies
  the changes. A reconcile job on the scheduler calls `get` for backed
  work items changed in the last day, to cover lost deliveries.
- **Writes.** A change to one of those fields in Imbi calls the plugin
  first. Imbi writes its own copy only when the call succeeds. A failed
  call returns the error and writes nothing.
- **A turn goes out as the assignee.** Jira has one assignee, so the
  Jira integration can write the holder of the most recently opened
  turn to it, so Jira boards keep working during the move. Every agent
  turn writes one Jira user for the integration, `Imbi`. Jira does not
  see which agent holds the work; Imbi tracks the real agent and owner,
  and the Jira comment Imbi writes names them.
- **Imbi-only fields.** Owner, turns, projects, pull request links,
  runs, and stage are Imbi's. A turn is copied out as the assignee
  (above).
- **One credential per system.** The plugin uses one integration per
  organization. Every person, agent, and workflow acts through it, with
  the Imbi actor named in the comment or change it makes.
- **Comments come in ([H3][req-h-participation-and-channels]).** Comments on the issue and on
  linked pull requests become `comment.added` events with their source.
  A Turn step that reads replies reads these.

A native work item has no external issue. Imbi is its only source of
truth.

### Pull requests and live

A pull request is linked to a work item when its title, branch, or body
contains the work item's short id or its external key. A person can link
or unlink one by hand. The pr-sync capability supplies the pull request
state behind the `pr.*` facts.

A pull request closed without merging stays linked but is left out of
every `pr.*`, live, and released fact. When #50 is closed and replaced
by #51, the facts wait on #51 alone.

A pull request linked after the run has passed the steps that wait on
`pr.*` facts is only linked. The run does not go back, and a closed
work item stays closed. A step still ahead of it in the run sees the
new pull request in its facts.

Live is per project, and what it means depends on the project type:

- **Deployable** (an HTTP API, a consumer): the project is live in an
  environment when the merge commit of every linked pull request in that
  project is in the project's current deploy to that environment. Fact:
  `live_in.<environment>.<project>`.
- **Releasable** (a library): the project has no deploys. It is released
  when a release tag contains the merge commit of every linked pull
  request in that project. Fact: `released.<project>`, with the version
  in `released_version.<project>`.

`live_in.<environment>` is true when every deployable project with a
linked pull request is live there. `released` is true when every
releasable one is released. A library fix that must reach a service is
verified on that service: add the service to the work item and link the
pull request that bumps the dependency. Imbi computes all of this from
its deployment and release records. The first time a work item becomes
live in an environment, Imbi writes one `live.reached` event, naming the
projects and the deploys; the first release of a releasable project
writes `released`.

### Notifications

- **A new turn** writes a notification for its holder and for each
  "also tell" person to the `notifications` outbox, in the same
  transaction as the `turn.opened` event.
- **Delivery** goes through a new `notify` plugin capability. The first
  plugin is Slack, which sends DMs and channel posts. The slackbot keeps
  handling inbound Slack (asks, replies, buttons) and passes them to
  imbi-api.
- **Quiet hours** are set for the organization and per person. A
  notification inside quiet hours waits for the next allowed time.
- **Scheduled messages** are scheduler jobs: the morning list (from
  Waiting on me), reminders (from Turn step settings), and digests (from
  saved views).

### Priority

`priority` is a field on the work item, the same for everyone: one of
`highest`, `high`, `medium`, `low`, `lowest`, or unset.

- On a backed item it comes from the external system through
  `priority_map`, and a change in Imbi writes through the plugin.
- Otherwise a person with `work_item:write` sets it, a workflow sets it
  with an Update work item step, or an agent such as triage sets it
  through the Imbi MCP.
- Branch conditions read it.
- Waiting on me and the morning list sort by it.

There is no personal priority in v1. HandoffBee's per-person star is
not carried over.

### Permissions

| Permission | Allows |
|---|---|
| `work_item:read` | List and read work items and their events |
| `work_item:create` | Create a work item and link an external issue |
| `work_item:write` | Edit, comment, set roles, hand a turn, change status, link pull requests |
| `work_item:delete` | Delete a work item |

The member role gets read, create, and write by default. Choosing an
outcome on a Turn needs a turn on that step, or `work_item:write` and a
place in the step's "turn goes to" list.

### Realtime

When ADR 0023 is accepted, work item writes publish to
`work_item:<org>:<short_id>`, and changes to a person's Waiting on me
publish to `user:<user_id>`.

### Not decided here

- Leaving Jira. When the organization stops using Jira, its backed
  work items must become native, with Imbi owning every field. Whether
  that happens in one switch per organization or item by item is open.
- Leaving HandoffBee. HandoffBee will hold open asks when Imbi replaces
  it. Whether they are copied into Imbi as work items or left to finish
  in HandoffBee is open.
- A retention policy for work item events.

## Consequences

- Imbi has two kinds of work record. An agent task is one agent on one
  discrete ask; a work item is the subject those tasks share. Waiting on me shows both
  as one list; the API, permissions, and storage keep them apart.
- `agent_runtime.tasks` and `workflow_runtime.runs` gain a nullable
  column. Both need migrations that keep the old code working during a
  rolling deploy.
- ADR 0021 changes:
    - **Send-backs and rounds.** The drawn graph stays acyclic, but a
      step outcome can send work back to an earlier node. That starts a
      new round, which re-runs the target and everything downstream.
      Each send-back has a cap (default 3), after which the step takes
      `Too many rounds`.
    - **For each.** A step can run once per project or once per pull
      request on the work item. It finishes when every instance
      finishes, and the ports aggregate worst first.
    - **Parked steps.** A waiting step holds no lease. It sleeps until
      a work item event, a fact change, or a timer wakes it.
    - **No limit.** Max run time accepts "No limit", since a driving
      run can last weeks.
    - **Four step types.** Turn, Gate, Branch, and Update work item.
    - **Work item workflows.** A new kind of workflow with no trigger.
      Creating or reopening a work item starts one.
    - **Agent step.** It gains "on behalf of", the role that owns the
      task, and verdicts, the named outcomes the agent reports, each a
      port.
- The task owner can change after creation, when someone hands the
  agent's turn to another person. ADR 0020 already allows reassignment;
  the `owner.changed` event names the work item turn as the reason.
- Agents need the work item MCP tools to read the shared log. A task on
  a work item that does not read it works, but repeats context the log
  already holds.
- A backed work item depends on its external system for writes to the
  fields it owns. An outage in Jira blocks those writes in Imbi; reads
  and Imbi-only fields keep working.
- Webhooks from Jira need a gateway Webhook per organization and a
  verified signature.
- Fact watches are evaluated inside imbi-api after each work item write
  commits. A slow fact delays the write path.
- Adding the stream means updating `TOPICS`, `clickhouse/schemata.toml`,
  and `compose.ci.yaml` `IGGY_TOPICS`, and restarting `iggy-connect` in
  each environment after the first deploy.
- HandoffBee keeps running until Turn, Gate, send-backs, and
  notifications ship. Until then the two run side by side on Jira.

[req]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md
[req-f-tasks]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#f-tasks
[req-g-delegation]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#g-delegation
[req-h-participation-and-channels]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#h-participation-and-channels
[req-i-human-gates]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#i-human-gates
[req-o-inbox-and-transcript]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#o-inbox-and-transcript
[req-r-deterministic-decisioning-and-routing]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#r-deterministic-decisioning-and-routing
