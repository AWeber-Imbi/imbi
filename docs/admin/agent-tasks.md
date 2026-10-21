# Agent Tasks

An **agent task** is one piece of work for one [agent](agents.md). Each
task has a short id, for example `T-42`. The id is unique in the
organization.

A task has:

- A title and a description. The description is the instruction for the
  agent.
- An owner. The owner is a person, and the agent asks the owner for input.
- A primary project. This is optional in the API.
- A budget in USD.
- An event log. Each change to the task writes an event. Events are never
  changed.

When Imbi makes a task, it pins the agent version, the prompt version, and
the base configuration version. A later change to the agent does not change
a task that exists.

A runner pod runs the task. See
[Agent Runners](../deployment/agent-runners.md). For the contract, see
[ADR 0020](../api/adr/0020-agent-task-contract.md).

## Permissions

| Permission | Lets you | Roles that have it |
|---|---|---|
| `agent_task:read` | See tasks, their events, usage, and the dashboard | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `agent_task:create` | Create tasks | `admin`, `developer`, `imbi-scheduler`, `imbi-gateway` |
| `agent_task:manage` | Pause, resume, cancel, and reassign tasks. Reply. Change relations and associated projects | `admin`, `developer` |
| `agent_task:resolve` | Answer feedback requests and resolve approvals | `admin`, `developer` |

You must also be a member of the organization. Only a person can resolve a
request, reply, or change relations. A service account gets `403`, also
when it has the permission.

## States

| State | Label | Meaning |
|---|---|---|
| `queued` | Queued | The task waits for a runner |
| `running` | Running | A runner works on the task |
| `blocked` | Needs input | The agent waits for an answer or an approval |
| `paused` | Paused | A person paused the task |
| `closed` | Closed | The task is done. It has an outcome |

A task also has a control value: `run`, `pause`, or `cancel`. People change
it. When a runner holds the task, the runner reads the control value and
stops or pauses. When no runner holds the task, the change applies at once.
A cancel then closes the task with `cancelled_by_human` and the reason
`cancelled_without_session`.

## Outcomes

A closed task has an outcome and, for all outcomes except `done_acted`, a
reason. The reason is a short slug, for example `project_not_found`.

| Outcome | Label | When |
|---|---|---|
| `done_acted` | Completed | The agent changed something |
| `done_nothing_to_act_on` | Nothing to do | The agent found nothing to do. With the reason `no_mutating_tool_call`, the agent did not report an outcome and called no tool that changes data |
| `failed_external` | Failed | The agent reports that it could not do the work, or the model or the runner failed. See [Task failure reasons](../deployment/agent-runners.md#task-failure-reasons) |
| `failed_at_gate` | Failed | The agent reports that it could not do the work |
| `partial_capped` | Partly done | The agent used all of its turns (`max_turns`) |
| `exceeded_ceiling` | Over budget | The cost went over the budget (`budget`), or the task ran longer than the task timeout (`task_timeout`) |
| `cancelled_by_human` | Cancelled | A person cancelled the task |
| `unhandled_no_actor` | Unhandled | The agent has no service account (`service_account_missing`) |
| `no_reason_to_run`, `request_expired`, `interrupted_by_operator`, `superseded`, `suppressed_duplicate`, `unmapped_subject`, `refused_rate_ceiling` | Not needed, Request expired, Interrupted, Superseded, Duplicate, Unmapped, Refused | Part of the contract. A harness can report them. Imbi and its runner do not set them in this release |

The agent reports its own outcome with the `report_outcome` tool:
`done_acted`, `done_nothing_to_act_on`, `failed_external`, or
`failed_at_gate`. The last report wins.

## Create a task

You need `agent_task:create`. There are three places to start:

- Click **+** in the top bar, then **New Agent Task**.
- On **Agents > Tasks**, click **New task**.
- On an agent's detail page, click **Run**. The dialog opens with that
  agent selected.

In the **New task** dialog:

1. In **What should the agent do?**, describe the outcome that you want.
   The first line, without its links, becomes the title (96 characters
   maximum).
2. Optional: paste a link. The dialog shows it as the **Source**: a Sentry
   issue, a pull request, a Slack thread, or a link.
3. Select an **Agent**. The list shows enabled agents only.
4. Select a **Project**. Archived projects are not in the list.
5. Click **Create task**.

The task starts as **Queued**. You are its owner. The task page opens.

### With the API

```http
POST /organizations/{org}/agent-tasks/
```

```json
{
  "agent_slug": "triage",
  "title": "Check the failing build",
  "description": "Find why the main branch build fails, and open a fix.",
  "project_id": "<project id>",
  "budget": "2.50",
  "idempotency_key": "build-1234"
}
```

`project_id`, `budget`, and `idempotency_key` are optional. A repeat with
the same `idempotency_key` returns the first task with `200`. A disabled
agent returns `409`.

## Triggers

The trigger of a task says what started it. It comes from the caller, not
from the request body.

| Trigger | Origin | Made by | Owner |
|---|---|---|---|
| Manual | `human` | A person: the UI, the API, or the Slack bot | That person |
| Schedule | `schedule` | The `imbi-scheduler` service account | The person accountable for the scheduled task |
| Webhook | `webhook` | The `imbi-gateway` service account | The person who last edited the webhook |
| Delegation | `task` | A parent task, when its agent calls a subagent | The owner of the parent task |

Any other service account gets `403`. The owner of a schedule or webhook
task must be an active user, a member of the organization, and hold
`agent_task:create`.

A [workflow](workflows.md) `agent` step also makes tasks. The task keeps
the origin of the workflow run.

### Schedules

Use a scheduled task with an `api` target that posts to
`/agent-tasks/`. The scheduled task must name the organization. See
[Scheduled Tasks](../scheduler/tasks.md#api). A retry of a run returns the
first task.

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

The action makes one task for each matched project. A redelivery makes no
second task.

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
task, and replies with a link. You own the task. Your Slack user must map
to an Imbi user that has `agent_task:create`.

The agent cannot read Slack. The bot puts what the agent needs in the
description.

!!! note
    An install with a CMS version of `imbi-slackbot/system` keeps that
    version. Add the **Agent Tasks** section of the packaged prompt to it.
    See [Prompts](prompts.md).

## The Tasks inbox

Open **Agents > Tasks**. The inbox has four groups:

| Group | Tasks |
|---|---|
| Human input required | Tasks with an open request, also paused tasks with an open request. The oldest request is first |
| Running | Running tasks, and paused tasks without an open request |
| Queued | Tasks that wait for a runner |
| Recently closed | Closed tasks, newest first |

- The filter field matches the title, the id, the agent, and the project.
- **State** and **Assignee** filter by state and owner. **My tasks** shows
  only your tasks.
- The inbox loads more tasks as you scroll. A count shown as `N+` can still
  grow.
- The inbox and the open task update without a reload.

The **Tasks** item in the Agents sidebar shows the number of tasks that
wait on you. The **Agents** menu in the top bar shows "N waiting on you".

A task URL is `/agents/tasks/<organization slug>/<short id>`.

## Task detail

The header shows the id, the title, the state, the agent, the project, the
trigger, the duration, and the cost. It also has a timeline of the phases
of the task.

| Tab | What it shows |
|---|---|
| Overview | The description, the latest todo list, the owner, the budget, the cost, the tokens, the prompt version, and the outcome |
| Input required | The requests of the agent. See [Answer a request](#answer-a-request) |
| Conversation | Turns, replies, and state changes. See [Reply](#reply) |
| Actions taken | The tool calls. Click a call to expand it. Calls of a subagent show under their parent call |
| Signals and checks | The latest report of each check, with its value, baseline, and verdict. The tab count shows the failing checks |
| Related tasks | Dependencies, the parent task, and child tasks |
| Associated projects | The primary project and the other projects of the task |

### Pause, resume, and reassign

You need `agent_task:manage`. The controls do not show on a closed task.

- Click the pause button to pause the task. Click it again to resume.
- Click the reassign button, enter the email of the new owner, and click
  **Reassign**. The new owner must be a member of the organization.

To cancel a task, use the API:
`POST /organizations/{org}/agent-tasks/{short_id}/cancel`.

## Answer a request

An agent can open two kinds of request. Each request moves the task to
**Needs input**.

- **Feedback**: a question. Click an option, or write an answer and click
  **Send answer**.
- **Approval**: approval for an action, for example a tool call that needs
  approval. Click **Approve** or **Reject**.

You need `agent_task:resolve`. The request records who answered, when, and
from which channel.

- When another person answers first, the request closes in place and shows
  who answered.
- You cannot answer an expired request.
- An approval covers the exact artifacts of the request. When the artifacts
  change, the agent opens a new request.

When the last open request is resolved, a **Needs input** task changes:

- A runner holds it and its control value is `run`: it goes to
  **Running**.
- No runner holds it: it goes to **Queued**, or to **Paused** when its
  control value is `pause`.

## Reply

On the **Conversation** tab, write in the reply field. You need
`agent_task:manage`.

- **Reply** sends the text to the agent. The agent reads it at its next
  turn.
- **Reply and hold** sends the text and pauses the task. Resume the task
  when the agent can go on.

A reply or an answer can be up to 64 KiB.

## Relations and associated projects

You need `agent_task:manage` to change them.

**Related tasks**: click **Link task**. Find a task, then select the
relation:

| Relation | Means |
|---|---|
| Requires | This task needs the other task first |
| Blocked by | The same as Requires |
| Required by | The other task needs this task first |
| Blocks | The same as Required by |

A task cannot require itself. Parent and child rows come from delegation.
You cannot change them.

**Associated projects**: click **Link project** to add a project. The
primary project is first, with the badge **Primary**. You cannot associate
the primary project again. A deleted project shows its slug and "No longer
available". You can still remove it.

When the log of a closed task moves to the archive, its relations and
projects cannot change.

## Budgets

The budget of a task is a hard limit in USD.

- It defaults to the **Task budget** of the agent.
- A create can set a lower budget, never a higher one. A higher budget
  returns `422`.
- With no budget on the task or the agent, the task has no limit.

The runner reports the tokens of each model call. Imbi calculates the cost
from the prices in [AI Models](ai-models.md), including cache reads and
writes. When the cost goes over the budget, Imbi closes the task with
`exceeded_ceiling` and the reason `budget`. A model with no price counts as
$0.

The monthly cost cap of an agent is different. It only gives warnings. See
[Usage](agents.md#usage).

## Operations Log

A task with a project writes rows to the Operations Log, with the entry
type **Agent Task**:

- One row when a person resolves a request, for example
  `T-42: approval request approved`.
- One row when the task closes, for example `T-42 closed: done_acted`.

A row has no request or reply text. A task with no project writes no rows.
You cannot add or change an **Agent Task** row with the Operations Log API.
