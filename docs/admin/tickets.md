# Tickets

A **ticket** is one piece of work for one [agent](agents.md) or one
person (a [person ticket](#person-tickets)). Before
release A of [ADR 0028](../api/adr/0028-tasks-become-tickets.md), a
ticket was named an "agent task". Each ticket has a short id, for
example `T-42`. The id is unique in the organization.

A ticket has:

- A title and a description. The description is the instruction for the
  agent.
- An owner. The owner is a person, and the agent asks the owner for input.
- Zero or more projects. The agent gets the repository of each project.
- A budget in USD.
- A priority: **Low**, **Normal**, **High**, or **Urgent**. The default
  is **Normal**.
- An event log. Each change to the ticket writes an event. Events are never
  changed.

When Imbi makes a ticket, it pins the agent version, the prompt version, and
the base configuration version. A later change to the agent does not change
a ticket that exists.

A runner pod runs the ticket. See
[Agent Runners](../deployment/agent-runners.md). For the contract, see
[ADR 0020](../api/adr/0020-agent-task-contract.md).

## Permissions

| Permission | Lets you | Roles that have it |
|---|---|---|
| `ticket:read` | See tickets, their events, usage, and the dashboard | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `ticket:create` | Create tickets | `admin`, `developer`, `imbi-scheduler`, `imbi-gateway` |
| `ticket:manage` | Pause, resume, cancel, reassign, and hand off tickets. Reply. Change relations and associated projects | `admin`, `developer` |
| `ticket:resolve` | Answer feedback requests and resolve approvals | `admin`, `developer` |
| `ticket:delete` | Delete closed tickets | `admin` |

Before ADR 0028 these permissions were `agent_task:*`. `imbi-api
setup-permissions` gives each role that has an old permission the new
one, then removes the old one. An API key or token scope that names an old
permission still gives the new permission with the same action.

You must also be a member of the organization. The permissions come from
your role in that organization only. Only a person can resolve a
request, reply, or change relations. A service account gets `403`, also
when it has the permission.

## States

| State | Label | Meaning |
|---|---|---|
| `held` | Held | A gating prerequisite holds the ticket. A runner does not take it |
| `queued` | Queued | The ticket waits for a runner |
| `running` | Running | A runner works on the ticket |
| `blocked` | Needs input | The agent waits for an answer or an approval |
| `paused` | Paused | A person paused the ticket |
| `open` | Open | A person ticket that its assignee has not started |
| `in_progress` | In progress | The assignee of a person ticket started work |
| `closed` | Closed | The ticket is done. It has an outcome |

An agent ticket is never `open` or `in_progress`; a person ticket is
never `queued`, `running`, or `paused`. A person ticket is `blocked` when
its assignee waits on something.

A ticket also has a control value: `run`, `pause`, or `cancel`. People change
it. When a runner holds the ticket, the runner reads the control value and
stops or pauses. When no runner holds the ticket, the change applies at once.
A cancel then closes the ticket with `cancelled_by_human` and the reason
`cancelled_without_session`.

## Outcomes

A closed ticket has an outcome and, for all outcomes except `done_acted`, a
reason. The reason is a short slug, for example `project_not_found`.

| Outcome | Label | When |
|---|---|---|
| `done_acted` | Completed | The agent changed something |
| `done_nothing_to_act_on` | Nothing to do | The agent found nothing to do |
| `failed_external` | Failed | The agent reports that it could not do the work, the agent stopped without a report (`no_outcome_reported`), or the model or the runner failed. See [Task failure reasons](../deployment/agent-runners.md#task-failure-reasons) |
| `failed_at_gate` | Failed | The agent reports that it could not do the work |
| `partial_capped` | Partly done | The agent used all of its turns (`max_turns`) |
| `exceeded_ceiling` | Over budget | The cost went over the budget (`budget`), or the ticket ran longer than the task timeout (`task_timeout`) |
| `cancelled_by_human` | Cancelled | A person cancelled the ticket |
| `unhandled_no_actor` | Unhandled | The agent has no service account (`service_account_missing`) |
| `no_reason_to_run`, `request_expired`, `interrupted_by_operator`, `superseded`, `suppressed_duplicate`, `unmapped_subject`, `refused_rate_ceiling` | Not needed, Request expired, Interrupted, Superseded, Duplicate, Unmapped, Refused | Part of the contract. A harness can report them. Imbi and its runner do not set them in this release |

The agent reports its own outcome with the `report_outcome` tool:
`done_acted`, `done_nothing_to_act_on`, `failed_external`, or
`failed_at_gate`. The last report wins. When the agent stops without a
report, the runner asks it once more to report. A ticket whose agent
still does not report fails with `failed_external` and the reason
`no_outcome_reported`, even when the agent changed something: Imbi cannot
tell whether the work is done. Tell the agent to call `report_outcome` in
its prompt if it often forgets.

When a ticket is created or changes its status, Imbi starts each active
[workflow](workflows.md) with a **Ticket state changed** trigger
(`ticket_state_changed`) that matches the change.

## Person tickets

A person ticket goes to one person (the **assignee**), by email. The
assignee must be a member of the organization. The owner and the
assignee can be different people. A runner never takes a person ticket,
and it has no budget, sessions, or usage.

A person ticket starts **Open**. Its assignee, or a person with
`ticket:manage`, moves it on the ticket page or with
`POST /organizations/{org}/tickets/{id}/status`:

| From | To | Body |
|---|---|---|
| `open` | `in_progress` | `{"status": "in_progress"}` |
| `open`, `in_progress` | `blocked` | `{"status": "blocked", "reason": "Waiting on ops"}` |
| `blocked` | `open`, `in_progress` | `{"status": "in_progress"}` |
| every status | `closed` | `{"status": "closed", "outcome": "done_acted"}` |

The outcome of a person ticket is `done_acted`, `done_nothing_to_act_on`,
`superseded`, or `cancelled_by_human`. Pause, resume, cancel, and retry
apply to agent tickets only. A `held` person ticket opens when its gating
prerequisites are done.

You cannot retry an agent ticket that a workflow step made. The retry
returns `409` with `workflow_step_task`. Start a new run of the workflow
instead. See [Agent task](workflows.md#agent-task).

## Hand off a ticket

A ticket can go from an agent to a person, from a person to an agent,
and from a person to another person. It keeps its id, log, owner,
parent, dependencies, projects, and cost. On the ticket page, click
**Hand off** (the arrows icon), or use
`POST /organizations/{org}/tickets/{id}/hand-off`:

```json
{"assignee_kind": "person", "assignee": "ops@example.com", "note": "Merge the PR"}
{"assignee_kind": "agent", "agent_slug": "triage"}
```

The owner, the assignee, and people with `ticket:manage` can hand off a
ticket. The status changes in the same write:

| From | To a person | To an agent |
|---|---|---|
| `queued`, `paused` | `open` | |
| `open`, `in_progress` | | `queued` |
| `blocked` | `open` | `queued` |
| `held` | `held` | `held` |

- Imbi refuses a handoff while a runner holds the ticket (`409
  session_open` or `chain_pinned`). To take a running ticket, pause it,
  and hand it off when its session closes.
- Each open request closes as **Withdrawn**, with no answer.
- An agent gets the ticket at the agent version that it has now. The
  task budget of the agent caps the budget of the ticket; a ticket with
  no budget gets the task budget. The budget counts the cost
  of every agent period of the ticket. The task timeout counts from the
  first session after the last handoff.
- An agent ticket cannot go to another agent.
- From a person to another person, only the assignee changes
  (`assignee.changed`). Other handoffs write `handed_off`.

An agent gives its own ticket to a person with its `hand_off` tool, with
a note. The default person is the owner. The tool ends the session; the
ticket does not get an outcome. Use it when a person must do the rest of
the work, or must decide something that can take days. A new session of
an agent reads the handoffs and their notes in the ticket history.

## Create a ticket

You need `ticket:create`. There are three places to start:

- Click **+** in the top bar, then **New Ticket**.
- On the **Tickets** page, click **New ticket**.
- On an agent's detail page, click **Run**. The dialog opens with that
  agent selected.

In the **New ticket** dialog:

1. In **Describe the work**, describe the outcome that you want. When
   you stop typing, a model writes the **Subject** (tagged **AI**).
   The model writes a subject only for a description of 20 characters
   or more. Until it answers, for a shorter description, or when no
   model is available, the first line without its links is the subject
   (tagged **Auto**, 96 characters maximum). Type in **Subject** to use
   a different one.
2. Optional: paste a link. The dialog shows it as the **Source**: a Sentry
   issue, a pull request, a Slack thread, or a link.
3. In **Assign to**, select **Agent** and an agent, or **Person** and a
   person. The agent list shows enabled agents only, with the agents that
   you used last at the top.
4. Optional: select a **Type** (**Bug**, **Task**, or **Feature**), a
   **Priority**, and a **Due** date. The defaults are **Task** and
   **Normal**.
   Type the due date as `mm/dd/yyyy`, for example `12/01/2026`, or pick it from the calendar. It can't be a day in the past.
5. Optional: add **Projects** and **Labels**. Archived projects are not in
   the list. See [Labels](#labels).
6. Complete the custom fields that the dialog asks for. It asks for each
   required field with no default of the `Ticket` blueprints that match
   the type, the priority, and the labels. See
   [Custom fields](#custom-fields).
7. Optional: expand **Owner** to make another person the owner (needs
   `ticket:manage`), **Team** to set the team that owns the work,
   **Roles** to put people in named roles, or
   **Relations** to set a parent and prerequisites. A prerequisite is
   gating by default: clear **Gating** to make it information only.
8. Click **Create ticket**.

An agent ticket starts as **Queued**, a person ticket as **Open**. With
an open gating prerequisite, the ticket starts as **Held**. You are its
owner, unless you selected a different **Owner**: when that change
succeeds, that person is the owner. The ticket page opens.

### With the API

```http
POST /organizations/{org}/tickets/
```

```json
{
  "agent_slug": "triage",
  "title": "Check the failing build",
  "description": "Find why the main branch build fails, and open a fix.",
  "project_ids": ["<project id>", "<project id>"],
  "budget": "2.50",
  "idempotency_key": "build-1234"
}
```

`project_ids`, `budget`, `idempotency_key`, `type` (`bug`, `task`, or
`feature`), `due_date` (`YYYY-MM-DD`), `labels`, `roles`, `team` (a team
slug), and `custom_fields` are optional. A `team` that is not a team of
the organization returns `422` with `team_not_found`. A repeat with
the same `idempotency_key` returns the first ticket with `200`. A disabled
agent returns `409`.

For a person ticket, send `"assignee_kind": "person"` and `"assignee":
"<email>"` instead of `agent_slug`, and no `budget`. Send `requires` to
add prerequisites, for example
`"requires": [{"short_id": "T-12", "gates": true}]`.

`roles` is an object of role names to member emails, for example
`{"reviewer": "dev@example.com"}`. Each person must be in the
organization. A workflow can read the roles and hand the ticket to the
person in a role: see [Assign ticket to role](workflows.md).

To change the type, the due date, the labels, the roles, the team, or
the custom fields later, send only those fields. You need `ticket:manage`.
Each change writes a `<field>.changed` event; `"due_date": null` clears
the due date and `"team": null` clears the team.

```http
PATCH /organizations/{org}/tickets/{short_id}
```

The prompt that writes the subject is `imbi-api/ticket-subject` in the
[prompt CMS](prompts.md). Edit it there, and choose its model; without a
model it uses the default Anthropic model of imbi-api. Run
`imbi-api setup-prompts` once to seed it on an install made before it
existed.

```http
POST /organizations/{org}/tickets/subject
```

```json
{"description": "The deployments list returns a 500 ..."}
```

The response has `subject`, and `degraded: true` when no model answered.
You need `ticket:create`.

## Custom fields

A [blueprint](blueprints.md#ticket-blueprints) of type `Ticket` adds
custom fields to the tickets that its filter matches: by type, priority,
and labels.

- The **New ticket** dialog asks for each required field with no
  default.
- The **Overview** tab shows the fields in the **Custom fields** card.
  With `ticket:manage`, click a value to change it.
- When the type or the labels change, other blueprints can match. Imbi
  keeps the values of fields that no longer match, and does not show
  them. Imbi never deletes a value.

Imbi checks every create, for every trigger. A required field with a
default gets the default. When a required field has no value, or a value
is not valid, the create returns `422`:

```json
{
  "detail": {
    "error": "custom_fields_invalid",
    "message": "The ticket is missing required custom fields",
    "missing": [
      {"field": "severity", "title": "Severity", "type": "string",
       "enum": ["sev1", "sev2", "sev3"]}
    ],
    "invalid": [
      {"field": "due_by", "message": "Input should be a valid date"}
    ]
  }
}
```

`missing` gives the property of each field, so that the caller can build
the value. A field that no matching blueprint declares is in `invalid`.
A `PATCH` checks only the fields that it sends; `null` clears one field.

To get the fields of a ticket before you create it:

```http
GET /organizations/{org}/tickets/schema?type=bug&priority=high&label=api
```

The response also has `filterable`: the fields of every `Ticket`
blueprint that the list can filter on, whatever the ticket.

Filter the list by a custom field with `filter=<field>:<op>[:<value>]`.
The operators are `eq`, `ne`, `in`, `not_in` (comma-separated values),
`exists`, and `not_exists`:

```http
GET /organizations/{org}/tickets/?filter=severity:in:sev1,sev2
```

Each automatic caller must send the required fields:

| Caller | How to send them |
|---|---|
| Schedule | Add `custom_fields` to the body of the `api` target. A failed run keeps the `422` body |
| Webhook | Add `custom_fields` to the handler config, as CEL expressions. See [Webhooks](#webhooks). The gateway logs the `422` |
| Workflow | Set `custom_fields` on the agent step. See [Agent task](workflows.md#agent-task) |
| Child ticket | An agent's child ticket is a `task` of `normal` priority with no labels. It gets the values of the parent for the fields that its matching blueprints declare. The values that the agent sends replace them, and the defaults fill the remaining fields. A required field gets its value from one of these three sources |

The agent of a ticket gets the custom fields that have a value in its
instruction. People and webhooks write the values, so the agent reads
them as data, not instructions.

## Labels

A label groups tickets across projects. Imbi stores each label in one
form, so `api`, `API`, and `api-` are the same label:

- Letters become lowercase.
- Each run of spaces, underscores, and hyphens becomes one hyphen.
- Leading and trailing punctuation goes.

The label field suggests the labels that the organization has, most used
first, with their ticket count. A label that exists always wins over a new
one. Click a label on a ticket to see every ticket with that label, or
filter by **Label** on the Tickets page. More than one label filter
matches tickets that have all of them.

```http
GET /organizations/{org}/tickets/labels?q=ap
GET /organizations/{org}/tickets/?label=api&label=web
```

## Backlog order

The **Queued** group on the Tickets page is the backlog: tickets that have
not started (**Held**, **Queued**, and **Open**). Ranked tickets come
first, in rank order; unranked tickets follow, newest first. Priority does
not change the order.

With `ticket:manage`, drag a ticket in the **Queued** group to set the
order. A drop on the top half of a row puts the ticket before that row; on
the bottom half, after it. **Move to top** on the ticket's **Overview**
does the same without a drag. When you drop a ticket after an unranked
ticket, the unranked tickets above it get ranks too, so the order that
you saw stays.

```http
POST /organizations/{org}/tickets/{short_id}/rank
```

```json
{"after": "T-12"}
```

`"after": null` puts the ticket first. The change writes a
`rank.changed` event. Agent runners do not use the rank: they take the
queued ticket with the highest priority (urgent, high, normal, then low),
then the oldest.

## Triggers

The trigger of a ticket says what started it. It comes from the caller, not
from the request body.

| Trigger | Origin | Made by | Owner |
|---|---|---|---|
| Manual | `human` | A person: the UI, the API, or the Slack bot | That person |
| Schedule | `schedule` | The `imbi-scheduler` service account | The person accountable for the scheduled task |
| Webhook | `webhook` | The `imbi-gateway` service account | The person who last edited the webhook |
| Delegation | `ticket` (`task` before ADR 0028) | A parent ticket, when its agent calls a subagent | The owner of the parent ticket |

Any other service account gets `403`. The owner of a schedule or webhook
ticket must be an active user, a member of the organization, and hold
`ticket:create`.

A [workflow](workflows.md) `agent` step also makes tickets. The ticket keeps
the origin of the workflow run.

### Schedules

Use a scheduled task with an `api` target that posts to
`/tickets/`. The scheduled task must name the organization. See
[Scheduled Tasks](../scheduler/tasks.md#api). A retry of a run returns the
first ticket.

### Webhooks

Use the gateway action `create_agent_task` (**Create Agent Task from
Webhook**). Add a rule to the webhook at **Admin > \<organization\> Admin >
Webhooks**:

1. Click **Add Rule**.
2. Enter a **Filter Expression (CEL)**. See
   [Webhook Rule Filter Expressions](../gateway/webhook-filter-expressions.md).
3. Enter the **Handler** `gateway-actions#create_agent_task`.
4. Enter the **Handler Config (JSON)**:

    ```json
    {
      "agent_slug": "triage",
      "title_expression": "payload.issue.title",
      "description_expression": "payload.issue.body"
    }
    ```

    `title_expression` and `description_expression` are CEL expressions.
    For a fixed text, use a quoted CEL string. `custom_fields` is
    optional. It maps a custom field name to a CEL expression, for example
    `{"severity": "'sev2'", "repository": "payload.repository.name"}`.
    `delivery_id_selector` is optional. It is a JSON pointer to the delivery id. The default is
    `/metadata/headers/x-github-delivery`.

5. Save the webhook.

The action makes one ticket for each matched project. A redelivery makes no
second ticket.

- The action runs only for a delivery with a verified signature. For
  GitHub, set the webhook secret to the secret of the GitHub hook.
- The action skips a delivery with no valid delivery id.
- The webhook text is not trusted. Imbi cuts the title to one line of 200
  characters. Imbi puts the text of the description after a fixed notice
  that tells the agent to treat it as data, not instructions.
- A webhook made before 2.38 has no owner. Edit and save it one time, or
  the action refuses it.

### Slack

Ask the Imbi Slack bot in plain words, for example: "@imbi create a task
to fix the issue in this thread and give it to mender". The bot finds the
agent, writes the title and the description from the thread, creates the
ticket, and replies with a link. You own the ticket. Your Slack user must map
to an Imbi user that has `ticket:create`.

The agent cannot read Slack. The bot puts what the agent needs in the
description.

!!! note
    An install with a CMS version of `imbi-slackbot/system` keeps that
    version. Add the **Agent Tasks** section of the packaged prompt to it.
    See [Prompts](prompts.md).

## The Tickets page

Click **Tickets** in the top bar. The page URL is `/tickets`. The page has
four groups:

| Group | Tickets |
|---|---|
| Human input required | Tickets with an open request, also paused tickets with an open request. The oldest request is first |
| Running | Running tickets, and paused tickets without an open request |
| Queued | The backlog: tickets that have not started, in backlog order. See [Backlog order](#backlog-order) |
| Recently closed | Closed tickets, newest first |

- The filter field matches the title, the id, the agent, and the project.
- **State**, **Assignee**, **Agent**, **Label**, and **Team** filter the
  list. Each custom field with a fixed set of values (an enum or a
  boolean) is also a filter. **My
  tickets** shows only your tickets.
- A ticket with a priority other than **Normal** shows its priority. A bug
  or a feature shows an icon for its type. A due date shows in amber when
  it is two days away or less, and in red when it is past.
- The page loads more tickets as you scroll. A count shown as `N+` can still
  grow.
- The page and the open ticket update without a reload.

### Group by workflow run

**Group by workflow run** (the layers button next to **Reveal in list**)
shows one row per unit of work instead of one row per ticket. A unit is
the tickets that one workflow run made, with their child tickets, or a
ticket that no run made, with its child tickets. The browser remembers the
choice.

- The filters pick the tickets, and the units are made from them.
- A unit is in the most urgent group of its tickets. For example, a run with
  one running ticket and three closed tickets is under **Running**.
- A unit row shows the subject of the run (a Jira key, for example) and the
  workflow, a bar for each ticket the run started (oldest first), and the
  number of tickets and child tickets.
- Click the arrow to list the tickets of the unit. Child tickets are
  indented; the last two show, with a button for the rest. **Open run**
  opens the run page.
- The footer shows the number of rows and the number of tickets in them.
- The API is `GET /organizations/{org}/tickets?group_by=run`; the counts and
  position endpoints take `group_by=run` too.

## Agent activity

A ticket row and the ticket header show an icon for what the agent does
now. Hover the icon to see the text. Person tickets and tickets that are not
active (queued, held, paused, or closed) show no icon.

| Icon | Activity | When |
|---|---|---|
| Activity (blue, pulses) | Working | The ticket is running and nothing below applies |
| Fork (blue) | Waiting on a subagent | The ticket is running and a child ticket is not closed |
| Shield with a question mark (amber) | Waiting on an approval | The ticket has an open approval request |
| Speech bubble with a question mark (amber) | Waiting on a person | The ticket has an open feedback request |
| Warning triangle (red) | Stalled | The ticket is running and its session sent no heartbeat in 60 seconds |

The API sends it as `agent_activity` on `GET /organizations/{org}/tickets`
and `GET /organizations/{org}/tickets/{id}`.

## Waiting on me

The **Tickets** item in the top bar shows the number of items that wait
on you. Click the hourglass on the Tickets page, or open
`/tickets/waiting`, to see them. The page has three lists:

| List | Items |
|---|---|
| Questions on your tickets | Open requests that have not expired, on the tickets that you own and that are not closed. Paused tickets are included |
| Assigned to you | Person tickets assigned to you that are not closed |
| Held: a prerequisite failed | Held tickets that you own with a gating prerequisite that closed with an outcome other than `done_*`, with those prerequisites |

The count is the number of items in the three lists. The API is
`GET /organizations/{org}/tickets/waiting`: it sends the count, and the
lists with `?lists=true`. A caller that is not a person gets a count of
`0`.

A ticket URL is `/tickets/<organization slug>/<short id>`. Add `/<tab>` to
open a tab. Old `/agents/tasks/...` URLs go to the new URL.

## Ticket detail

The header shows the id, the title, the priority (when it is not
**Normal**), the state, the agent, the project, the
trigger, the duration, and the cost. It also has a timeline of the phases
of the ticket.

- Hover the duration to see the turns, the model requests, the tool calls, the model time, the tool time, and the output speed.
- Hover the cost to see the share of the budget the ticket used, its tokens by kind (uncached input, cache read, cache write, and output), the cache hit rate, and the cost of each model when the ticket used more than one.

| Tab | What it shows |
|---|---|
| Overview | The description, the latest todo list, the owner, the priority, the team, the custom fields, the budget, the cost, the tokens, the prompt version, and the outcome |
| Input required | The requests of the agent. See [Answer a request](#answer-a-request) |
| Activity | The events of the ticket, as a conversation, as a trajectory of every event, or as statistics for each turn. See [Read the activity](#read-the-activity) |
| Signals and checks | The latest report of each check, with its value, baseline, and verdict. The tab count shows the failing checks |
| Related tasks | Dependencies, the parent ticket, and child tickets |
| Associated projects | The projects of the ticket |

### Read the activity

The **Activity** tab shows the events of the ticket in three views. Pick a view with the switch at the start of the toolbar. The tab opens on the view you used last.

- The search field matches any text in the view and marks each match. It keeps its text when you switch views.
- The copy button copies the conversation loaded so far as Markdown, or the ticket and its events as JSON.

#### Conversation

The **Conversation** view shows the ticket as turns. A turn starts with a person's input, then the agent's work, then the agent's reply.

- The work of a turn folds under one line, such as **Worked for 37s**. Click the line to open or close it.
- Inside a turn, the work is grouped by kind, such as "ran 3 commands" or "read 2 files". A group with a failed or denied call is red.
- Each tool call shows the tool, a summary of its input, and its duration. Open a call to see its input and output. Bash calls show the command and output in a terminal pane, and Edit and Write calls show a diff.
- **Open in trajectory**, under an open call, opens the Trajectory view at that call.
- A subagent shows as a card: its description, its type, how many tools it called, its tokens and cost, and how long it ran, or **Running…** while it runs. Open the card to see what it was asked, its steps, and its answer, with **Open in trajectory**.
- Subagents that ran at the same time show under one **Ran N subagents in parallel** line, with their summed work time, tokens, and cost, and the time they took together.
- The line under a finished turn adds the subagents' share of its uncached tokens, such as **(18k in 7 subagents)**.
- An open request shows where the agent asked it, with its buttons.
- **Compact**, **Standard**, and **Verbose** set how much work shows open. The browser remembers the choice.
- **Narrow** and **Wide** set the reading width. The browser remembers the choice.
- When another view shows an event in the conversation, the turn that holds it opens, scrolls into view, and flashes for a moment. A subagent's event shows in the turn of the call that started it.

#### Trajectory

The **Trajectory** view shows every event of the ticket as one row: a person's input, a model turn, a tool call, a subagent's call, or a system event.

- The strip at the top shows the Input, Model, and Tools lanes over time. A failed call is red. Click a block to select its row. The clock button switches between actual duration and equal widths, and the browser remembers the choice.
- A tinted box on the strip marks the rows that the table shows, and moves as you scroll or fold. A thin line marks the selected event.
- The fold buttons fold or unfold the turns, the tool calls, and the subagent calls. A greyed-out button has nothing to fold, and its tooltip says why. The browser remembers which fold buttons are on, and folds the new rows of a running ticket the same way.
- A subagent's call shows its description, its type, how many tools it called, its tokens, cost, and duration. Subagent calls of one model request that ran at the same time sit under a **N subagents in parallel** row with their wall time, work time, tokens, and cost.
- Click a row to open the inspector. Its tabs depend on the row: a tool call has **Summary**, **Payload**, **Result**, and **Timing**, a subagent's call adds **Usage** with its tokens and cost, and most rows have **Raw**, which shows the raw event. The selected row, or the row of the selected request, is tinted and outlined.
- **Show in conversation**, at the bottom of the inspector, opens the Conversation view at the turn that holds the event.
- A link that ends in `#e` and an event number opens the trajectory at that event, with its row in the middle of the list. Clicking a row inside the view selects it and leaves the list where it is.

#### Statistics

The **Statistics** view shows one row for each turn, and a **Task total** row at the bottom.

- Hover a column heading to see how it is counted.
- **Context** is the size of the prompt: uncached input, cache read, and cache write. **Cache** is the share of it served from the cache.
- **Output**, **Model** (model time), **Tools** (tool time), and **Speed** (output tokens per model second) come from the model requests. The **Total** bar shows model time in purple, tool time in amber, and everything else in grey.
- Click a turn to show its steps, one for each model request. Click a step to read its answer.
- The speech-bubble button next to a turn opens the Conversation view at that turn.
- **Latest** shows the context of the last step of a turn, and **Cumulative** adds up its steps. The **±** button shows how much the context grew at each step. The browser remembers both choices.

Old links to the **Actions taken** and **Conversation** tabs open the Conversation view. Old links to the **Log** tab, and event links that end in `#e` and an event number, open the Trajectory view.

A ticket link without a tab opens the tab you used last.

### Pause, resume, cancel, reassign, and change the priority

You need `ticket:manage`. The controls do not show on a closed ticket.

- Click the pause button to pause the ticket. Click it again to resume.
- Click the cancel button, then click **Cancel ticket** in the dialog. You
  cannot resume a cancelled ticket. The API is
  `POST /organizations/{org}/tickets/{short_id}/cancel`.
- Click the reassign button, enter the email of the new owner, and click
  **Reassign**. The new owner must be a member of the organization.
- On the **Overview** tab, click a **Priority**. The API is
  `POST /organizations/{org}/tickets/{short_id}/priority` with
  `{"priority": "high"}`. The change writes a `priority.changed` event.

### Reopen a closed ticket

The owner, the assignee, and people with `ticket:manage` can reopen a
closed ticket. Click **Reopen**, write why, and click **Reopen ticket**.
The API is `POST /organizations/{org}/tickets/{short_id}/reopen` with
`{"reason": "Still broken"}`.

- The outcome and the close time clear. The `reopened` event records the
  old outcome and the reason.
- A person ticket returns to `open`. An agent ticket returns to `queued`,
  and a runner starts a new session. The session history has the reason
  and the result of each earlier session: the last message that the
  agent wrote in it. The agent's reasoning and tool calls are not in the
  history.
- A reopen to an agent is checked as a handoff to an agent: you also
  need `ticket:create`, the owner must be able to make tickets, and the
  agent must be enabled. The ticket gets the agent version that the
  agent has now, and the task budget of the agent caps its budget. The
  task timeout counts from the first session after the reopen.
- The cost that the ticket spent stays. A ticket that closed on its
  budget runs out again at once when it reopens to an agent. Raise its
  budget or hand it off first.
- An agent ticket starts its own chain, also when an agent made it as a
  child of another ticket.
- To give the ticket a new assignee in the same request, add
  `"assignee_kind": "person", "assignee": "<email>"` or
  `"assignee_kind": "agent", "agent_slug": "<slug>"`.
- The log stays one log, also when it was archived.
- The request fails with 409 while a runner holds the chain of the
  ticket (`chain_pinned`), or while the workflow runs of its earlier
  changes have not all started (`triggers_pending`). Try again later.
- The reopen is a status change (`closed` to `open` or `queued`), and
  a ticket that closes again is another close. Each one starts its own
  `ticket_state_changed` workflow runs.

## Answer a request

An agent can open two kinds of request. Each request moves the ticket to
**Needs input**.

- **Feedback**: a question. Click an option, or write an answer and click
  **Send answer**.
- **Approval**: approval for an action, for example a tool call that needs
  approval. Click **Approve** or **Reject**.

You need `ticket:resolve`. The request records who answered, when, and
from which channel.

- When another person answers first, the request closes in place and shows
  who answered.
- You cannot answer an expired request.
- An approval covers the exact artifacts of the request. When the artifacts
  change, the agent opens a new request.

When the last open request is resolved, a **Needs input** ticket changes:

- A runner holds it and its control value is `run`: it goes to
  **Running**.
- No runner holds it: it goes to **Queued**, or to **Paused** when its
  control value is `pause`.

## Reply

While a ticket is open, the reply field shows at the bottom of every tab.
Write in the reply field. You need
`ticket:manage`.

- **Reply** sends the text to the agent. The agent reads it at its next
  turn:
    - During a session, the harness sends the reply when the current turn
      ends, and the agent starts a new turn to read it. A reply that comes
      while the agent waits for a request answer or for background work
      goes with the next turn.
    - A reply that comes after the last turn ended, after a turn that
      failed, or while the ticket stops is not sent in this session. A
      later session of the ticket reads it in the ticket history.
- **Reply and hold** sends the text and pauses the ticket. Resume the ticket
  when the agent can go on.

A reply or an answer can be up to 64 KiB.

## Relations and associated projects

You need `ticket:manage` to change them. The owner of a ticket can also
move it under a parent.

**Related tickets**: click **Link ticket**. Find a ticket, then select the
relation:

| Relation | Means |
|---|---|
| Requires | This ticket needs the other ticket first |
| Blocked by | The same as Requires |
| Required by | The other ticket needs this ticket first |
| Blocks | The same as Required by |
| Parent | Move this ticket, with its descendants, under the other ticket |

A ticket cannot require itself.

**Gating dependencies**: a dependency is a link only, unless you select
**Gating** in **Link ticket**. A gating prerequisite holds the dependent
ticket until the prerequisite closes with `done_acted` or
`done_nothing_to_act_on`.

- A `queued` ticket that gets an open gating prerequisite becomes `held`.
  The tab shows "Held: waiting on" and the prerequisites that hold it.
- A ticket that has started (not `queued` or `held`) refuses a gating
  prerequisite with `409` and `ticket_started`.
- When the last gating prerequisite closes with a `done_*` outcome, the
  dependent becomes `queued` (`paused` if a person paused it while it was
  held, `blocked` if it has an open request), in the same transaction as
  the close.
- When a gating prerequisite closes with another outcome, the dependent
  stays `held`. Cancel it, or remove the failed gate or make it a plain
  link. To use a replacement prerequisite, first remove or downgrade the
  failed gate, then add the replacement. A new prerequisite alone does not
  release the dependent. When you remove the last gate, or delete the
  prerequisite, the dependent is released.
- A held ticket refuses a harness session with `409` and `task_held`.
- Pause and resume change only the control value of a held ticket. Cancel
  closes it.

With the API: `PUT /organizations/{org}/tickets/{short_id}/requires/{prerequisite}`
with `{"gates": true}`. A request without `gates`, or with `false`, makes
an existing gate a plain link.

**Parent tickets**: a ticket can have one parent in its organization. A
ticket that an agent makes from its own ticket starts with that ticket as
its parent. A root ticket and its descendants are one piece of work, and
the owner of the root is accountable for it. The tab shows the parent, the
children, and the tree: its root and how many of its tickets are open.

- To move a ticket, select **Parent** in **Link ticket**. To make it a
  root, remove its **Parent** row.
- Holders of `ticket:manage` can move a ticket. The owner of the ticket
  can also move it in the UI or with the API.
- A move that makes a ticket its own ancestor gets `409` with
  `parent_cycle`.
- Open and closed tickets can move. A move changes no status, assignee,
  dependency, or chain. The ticket gets a `parent.changed` event.
- When you delete a ticket, its children become roots.

With the API: `PUT /organizations/{org}/tickets/{short_id}/parent` with
`{"parent": "T-5"}`, or `{"parent": null}` to make the ticket a root.

**Associated projects**: click **Link project** to add a project. The
oldest project is first. You can remove each project, also a project that
you set when you made the ticket. A deleted project shows its slug and "No
longer available". You can still remove it.

A secret grant that lists projects applies to a ticket only when the grant
lists all the projects of the ticket. The GitHub token of a ticket covers the
verified repositories of all its projects. The repositories must be in one
GitHub App installation.

When the log of a closed ticket moves to the archive, its relations and
projects cannot change.

## Budgets

The budget of a ticket is a hard limit in USD.

- It defaults to the **Task budget** of the agent.
- A create can set a lower budget, never a higher one. A higher budget
  returns `422`.
- With no budget on the ticket or the agent, the ticket has no limit.

The runner reports the tokens of each model call. Imbi calculates the cost
from the prices in [AI Models](ai-models.md), including cache reads and
writes. When the cost goes over the budget, Imbi closes the ticket with
`exceeded_ceiling` and the reason `budget`. A model with no price counts as
$0.

The monthly cost cap of an agent is different. It only gives warnings. See
[Usage](agents.md#usage).

## Operations Log

A ticket with a project writes rows to the Operations Log, with the entry
type **Agent Task**:

- One row when a person resolves a request, for example
  `T-42: approval request approved`.
- One row when the ticket closes, for example `T-42 closed: done_acted`.

A row has no request or reply text. A ticket with no project writes no rows.
You cannot add or change an **Agent Task** row with the Operations Log API.
