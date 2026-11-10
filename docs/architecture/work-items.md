# Work Items

This page shows how a work item moves between people and agents: the
parts, the data, and the flows. For the decisions and the reasons, see
[ADR 0024](../api/adr/0024-work-items.md). For agent tasks, see
[Agent Runtime](agent-runtime.md).

```mermaid
flowchart LR
    subgraph in[Inbound]
        JI[Jira webhook] --> GW[imbi-gateway<br/>sync_work_item]
        GH[GitHub webhook] --> GW
        SL[Slack: asks, replies, buttons] --> SB[imbi-slackbot]
        UI[Web UI and MCP]
    end
    subgraph api[imbi-api]
        WI[(work_items schema)]
        TR[Run starter and fact watcher]
        FX[Fact resolver]
        IQ[Waiting on me query]
    end
    WF[imbi-workflows<br/>driving run]
    AR[(agent_runtime)]
    H[Harness]
    SC[imbi-scheduler<br/>morning list, reminders, digests, reconcile]
    NP[notify plugin: Slack]
    IP[issues plugin: Jira, GitHub Issues]
    GW --> WI
    SB --> WI
    UI --> WI
    WI --> TR
    TR -->|start run, wake step| WF
    WF -->|turn, stage, roles| WI
    WF -->|agent step| AR
    AR --> H
    H -->|get_work_item, list_work_item_events| WI
    AR -->|agent_task.closed| WI
    FX -->|pr-sync, deployments| WI
    WI -->|outbox| NP
    WI -->|writes on backed items| IP
    SC --> IQ --> NP
    SC --> IP
```

## Parts

| Part | Owns |
|---|---|
| imbi-api | The `work_items` schema, every write, the run starter and fact watcher, the fact resolver, the Waiting on me query, the notification outbox |
| imbi-workflows | Driving runs: Turn, Gate, Branch, Update work item, and agent steps; parking and waking steps; send-back rounds |
| imbi-gateway | Verifies Jira and GitHub webhooks and calls `sync_work_item` |
| imbi-slackbot | Inbound Slack only: new asks, thread replies, button clicks. It calls imbi-api |
| imbi-scheduler | Morning lists, reminders, digests, quiet-hour releases, and the daily reconcile of backed work items |
| `issues` plugins | Jira and GitHub Issues: read, write, transition, comment, parse webhooks, map statuses and role fields |
| `notify` plugin | Slack: DMs and channel posts from the outbox |
| Harness | Runs agent tasks; reads the work item log through the Imbi MCP |

## Data

```mermaid
erDiagram
    work_items ||--o{ events : logs
    work_items ||--o{ work_item_projects : spans
    work_items ||--o{ role_members : has
    work_items ||--o{ turns : waits_on
    work_items ||--o{ pull_request_links : links
    work_items ||--o{ notifications : queues
    work_items |o--o| runs : driving_run_id
    runs }o--o| work_items : work_item_id
    tasks }o--o| work_items : work_item_id
    work_items {
        uuid id
        text short_id
        text status
        text stage
        text priority
        date due_on
        uuid owner_id
        uuid reporter_id
        uuid driving_run_id
        jsonb origin
        jsonb external_issue
    }
    work_item_projects {
        uuid work_item_id
        uuid project_id
        text source
    }
    turns {
        uuid work_item_id
        uuid run_step_id
        text holder_kind
        uuid holder_id
        uuid on_behalf_of
        text role
        timestamptz opened_at
        timestamptz closed_at
    }
    role_members {
        uuid work_item_id
        text role
        uuid user_id
        text source
    }
    events {
        uuid work_item_id
        bigint seq
        text type
        text actor_kind
        uuid actor_id
        jsonb payload
    }
    notifications {
        uuid id
        uuid user_id
        text kind
        timestamptz send_after
        text state
    }
```

`runs` is `workflow_runtime.runs` and `tasks` is `agent_runtime.tasks`.
Each gains a nullable `work_item_id`. `role_members` holds only people
set on the work item or mapped from an external field. Other role
resolvers (plugin, work item, pull requests) and facts are
computed when read and are not stored.

## Flow 1: a Jira issue starts a run

```mermaid
sequenceDiagram
    participant J as Jira
    participant G as imbi-gateway
    participant P as Jira plugin
    participant A as imbi-api
    participant W as imbi-workflows
    J->>G: issue_created
    G->>G: verify signature, CEL rule
    G->>P: parse_webhook(payload)
    P-->>G: field changes, issue type
    G->>A: sync_work_item(changes)
    A->>A: create W-142, type from type_map, events in one transaction
    A->>W: start the type's workflow, set driving_run_id
    W->>A: Update work item: status in_progress, stage Triage
```

Later changes to the issue update W-142 and write events. They wake
steps that wait on them, such as a Gate on the `workerbee-implement-fix`
label. They never start a second run.

## Flow 2: a Turn

```mermaid
sequenceDiagram
    participant W as imbi-workflows
    participant A as imbi-api
    participant N as notify plugin
    participant S as imbi-slackbot
    actor R as Product owner
    W->>A: Turn "PO acceptance": resolve turn goes to and also tell
    A->>A: turn.opened, stage.changed, outbox rows (one transaction)
    A->>N: deliver DMs outside quiet hours
    W->>W: park step (no lease), watch outcome and facts
    R->>S: clicks "Accept" in Slack
    S->>A: choose outcome (actor, channel slack)
    A->>A: outcome.chosen event
    A->>W: wake run
    W->>W: take the Accept port
```

A Turn set to give the turn to `everyone` opens one turn per person.
With two PR reviewers and done when `all`, Ana and Raj each get a row in
Waiting on me. The step waits for both, and one `Request changes` wins
over an `Approve`. With `any`, the first outcome closes both turns.

The outcome can also come from a reply. A model reads comments
(`comment.added`, including mirrored Jira and PR comments) and proposes
an outcome; a fact turning true can choose it too. Reminders and "if
nobody acts" are timers on the parked step. The scheduler sends
reminders through the same outbox.

## Flow 3: agents implement and review

```mermaid
sequenceDiagram
    participant W as imbi-workflows
    participant A as imbi-api
    participant H as Harness
    participant RV as Review task T-3190
    participant GH as GitHub
    W->>A: agent step "Implement", for each project, on behalf of Assignee
    A->>A: create task T-3184: work_item_id W-142, owner = assignee, watchers = role
    A->>A: turn.opened for the agent, on behalf of the assignee
    H->>A: claim T-3184
    H->>A: get_work_item, list_work_item_events
    H->>GH: open PR (W-142 in title, so it links)
    A->>A: fact pr.ready turns true
    A->>W: wake Gate "Ready PR" on the parallel branch
    W->>A: agent step "Review", on behalf of Review engineers
    A->>RV: create T-3190, owner = first review engineer
    RV->>GH: review: changes requested
    GH-->>A: review comment (gateway)
    A->>H: wake T-3184, new session (F17)
    H->>GH: push fix
    GH-->>A: push (gateway)
    A->>RV: wake T-3190, review the new revision (F18)
    RV->>GH: review: approved
    RV->>A: close with verdict approved
    A->>W: Review takes its approved port, then Turn "PO acceptance"
    GH-->>A: merged
    H->>A: report outcome, close
    A->>A: agent_task.closed on W-142 with summary and links
    A->>W: Implement done, Succeeded port, join "all" with the review branch
```

Before this, the triage task added the projects with
`add_work_item_project`. Implement runs for each project, so W-142 with
signup-api and email-lib has two implement tasks and two pull requests;
the diagram follows one. Review runs for each pull request.

The run fans out at Start build: one branch is Implement, the other is
the Ready PR Gate, the Review agent step, and the PO acceptance Turn.
The two tasks talk through the pull request, each woken by the other's
comments and pushes ([F17][req-f-tasks], [F18][req-f-tasks]). Rounds
stay inside the tasks, capped by each agent definition. If Implement takes its `Failed`
port, the engine cancels the parked steps on the review branch.

A person steps in when an agent asks. A request the review agent opens
(a question, an approval it cannot judge alone) opens a turn on W-142
for its task owner, the first review engineer, with the request as the
ask. Resolving the request closes that turn.

## Flow 4: a send-back

```mermaid
flowchart LR
    SB[Start build] --> IM[Implement<br/>agent] --> J{join all}
    SB --> RP[Ready PR<br/>Gate] --> RV[Review<br/>agent] --> PO[PO acceptance<br/>Turn] --> MG[Merge] --> J
    J --> LV[... live ...] --> VF[Verify<br/>agent]
    PO -. "Reject: send back to Ready PR, cap 3" .-> RP
    VF -. "not_fixed: send back to Start build, cap 2" .-> SB
    VF -->|cannot_verify, Failed| TT[Testers verify<br/>Turn]
    VF -->|Too many rounds| OW[Owner decides<br/>Turn]
```

Two kinds of send-back:

- **Same task.** A PO reject sends back to Ready PR. The reject comment
  on the pull request wakes the open Implement task, which pushes a fix.
  Ready PR, Review, and PO acceptance get round 2 step records. The
  review task for round 2 is new and reads the round 1 review from the
  work item log.
- **New task.** The verify agent's `not_fixed` verdict comes after the
  implement task closed, so it sends back to Start build. Implement runs
  again as a new task, which reads the verify agent's findings from the
  work item log.

When the verify agent cannot decide, it reports `cannot_verify` and the
testers get a Turn.

Earlier rounds stay in the run history. Past the cap, the outcome takes
`Too many rounds`.

## Flow 5: facts and live

```mermaid
sequenceDiagram
    participant D as Deployments
    participant A as imbi-api
    participant W as imbi-workflows
    D->>A: deployment to testing succeeded
    A->>A: fact resolver: for each project, every linked PR merge commit in its testing deploy?
    A->>A: fact.changed live_in.testing false to true, live.reached
    A->>W: wake Gate "Live in testing"
    W->>W: Met port, then Turn "Check in testing"
```

The resolver recomputes facts for the work items a change touches: a PR
update recomputes `pr.*` for the work items linked to it, and a deploy
recomputes `live_in.*` for open work items that list that project. A
library has no deploys: a release tag recomputes `released.*` for it
instead.

## Waiting on me

```mermaid
flowchart LR
    T[My open turns, including agent requests on work items] --> U[Union]
    R[Requests on my agent tasks with no work item] --> U
    U --> S[Sort: priority, due date, oldest wait]
    S --> B[Badge, page, morning list, reminders, MCP]
```

Role members who hold no turn on the item see it under My roles, which
is not counted in the badge.

## Who writes what

| Field | Written by |
|---|---|
| `turns`, `stage`, role members from a step | The driving run only |
| Title, description, status, labels, due, priority, role fields on a backed item | The external system through its plugin; Imbi writes through the plugin first |
| `owner_id` | People with `work_item:write` |
| Handing a turn | People with `work_item:write`; the run keeps waiting for the outcome |
| Task owner | imbi-api, from the agent step's on behalf of role |
| `agent_task.closed` | imbi-api, when a task on the work item closes |
| `fact.changed`, `live.reached` | The fact resolver in imbi-api |

[req-f-tasks]: https://aweber.ghe.com/team-members/gavinr-imbi-dev-env/blob/main/docs/agentic-platform-requirements.md#f-tasks
