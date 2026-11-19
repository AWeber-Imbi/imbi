# Tickets

A **ticket** is one piece of work for one [agent](agents.md). Before
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
| `ticket:manage` | Pause, resume, cancel, and reassign tickets. Reply. Change relations and associated projects | `admin`, `developer` |
| `ticket:resolve` | Answer feedback requests and resolve approvals | `admin`, `developer` |
| `ticket:delete` | Delete closed tickets | `admin` |

The old `agent_task:*` permissions still work until release B. Each check
accepts the old name or the new name with the same action.

You must also be a member of the organization. The permissions come from
your role in that organization only. Only a person can resolve a
request, reply, or change relations. A service account gets `403`, also
when it has the permission.

## States

| State | Label | Meaning |
|---|---|---|
| `queued` | Queued | The ticket waits for a runner |
| `running` | Running | A runner works on the ticket |
| `blocked` | Needs input | The agent waits for an answer or an approval |
| `paused` | Paused | A person paused the ticket |
| `closed` | Closed | The ticket is done. It has an outcome |

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
`failed_at_gate`. The last report wins. A ticket whose agent stops without
a report fails with `failed_external` and the reason
`no_outcome_reported`, even when the agent changed something: Imbi cannot
tell whether the work is done. Tell the agent to call `report_outcome` in
its prompt if it often forgets.

When a ticket closes, Imbi starts each active [workflow](workflows.md)
with a **Ticket closed** trigger (`ticket_closed`) that matches it. A
workflow saved with the old `task_completed` trigger still works.

## Create a ticket

You need `ticket:create`. There are three places to start:

- Click **+** in the top bar, then **New Ticket**.
- On the **Tickets** page, click **New ticket**.
- On an agent's detail page, click **Run**. The dialog opens with that
  agent selected.

In the **New ticket** dialog:

1. In **What should the agent do?**, describe the outcome that you want.
   The first line, without its links, becomes the title (96 characters
   maximum).
2. Optional: paste a link. The dialog shows it as the **Source**: a Sentry
   issue, a pull request, a Slack thread, or a link.
3. Select an **Agent**. The list shows enabled agents only.
4. Optional: select a **Priority**. The default is **Normal**.
5. Select a **Project**. Archived projects are not in the list.
6. Click **Create ticket**.

The ticket starts as **Queued**. You are its owner. The ticket page opens.

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

`project_ids`, `budget`, and `idempotency_key` are optional. A repeat with
the same `idempotency_key` returns the first ticket with `200`. A disabled
agent returns `409`.

The old `/organizations/{org}/agent-tasks/` paths still work until
release B. They are deprecated.

## Triggers

The trigger of a ticket says what started it. It comes from the caller, not
from the request body.

| Trigger | Origin | Made by | Owner |
|---|---|---|---|
| Manual | `human` | A person: the UI, the API, or the Slack bot | That person |
| Schedule | `schedule` | The `imbi-scheduler` service account | The person accountable for the scheduled task |
| Webhook | `webhook` | The `imbi-gateway` service account | The person who last edited the webhook |
| Delegation | `task` | A parent ticket, when its agent calls a subagent | The owner of the parent ticket |

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
    For a fixed text, use a quoted CEL string. `delivery_id_selector` is
    optional. It is a JSON pointer to the delivery id. The default is
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
| Queued | Tickets that wait for a runner |
| Recently closed | Closed tickets, newest first |

- The filter field matches the title, the id, the agent, and the project.
- **State** and **Assignee** filter by state and owner. **My tickets** shows
  only your tickets.
- A ticket with a priority other than **Normal** shows its priority.
- The page loads more tickets as you scroll. A count shown as `N+` can still
  grow.
- The page and the open ticket update without a reload.

The **Tickets** item in the top bar shows the number of tickets that
wait on you.

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
| Overview | The description, the latest todo list, the owner, the priority, the budget, the cost, the tokens, the prompt version, and the outcome |
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
- The work of a subagent shows under the call that started it.
- An open request shows where the agent asked it, with its buttons.
- **Compact**, **Standard**, and **Verbose** set how much work shows open. The browser remembers the choice.
- **Narrow** and **Wide** set the reading width. The browser remembers the choice.
- When another view shows an event in the conversation, the turn that holds it opens, scrolls into view, and flashes for a moment. A subagent's event shows in the turn of the call that started it.

#### Trajectory

The **Trajectory** view shows every event of the ticket as one row: a person's input, a model turn, a tool call, a subagent's call, or a system event.

- The strip at the top shows the Input, Model, and Tools lanes over time. A failed call is red. Click a block to select its row. The clock button switches between actual duration and equal widths, and the browser remembers the choice.
- A tinted box on the strip marks the rows that the table shows, and moves as you scroll or fold. A thin line marks the selected event.
- The fold buttons fold or unfold the turns, the tool calls, and the subagent calls. A greyed-out button has nothing to fold, and its tooltip says why. The browser remembers which fold buttons are on, and folds the new rows of a running ticket the same way.
- Click a row to open the inspector. Its tabs depend on the row: a tool call has **Summary**, **Payload**, **Result**, and **Timing**, and most rows have **Raw**, which shows the raw event. The selected row, or the row of the selected request, is tinted and outlined.
- **Show in conversation**, at the bottom of the inspector, opens the Conversation view at the turn that holds the event.
- A link that ends in `#e` and an event number opens the trajectory at that event.

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
  turn.
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
