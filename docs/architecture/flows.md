# Request and Trigger Flows

This page shows how work moves through Imbi in four common cases: a
browser request, a webhook, a scheduled task, and a workflow run. The
diagrams show the main path only. For the services, see the
[overview](overview.md).

## Browser request

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant C as Caddy
    participant A as imbi-api
    participant PG as Postgres (graph)
    participant CH as ClickHouse
    participant I as Iggy
    B->>C: GET /
    C-->>B: index.html (VITE_API_URL filled in) and UI files
    B->>C: GET /api/... with the access token in Authorization
    C->>A: same path (prefix kept)
    A->>A: authenticate the token, load the permissions of the principal
    A->>PG: read the catalog
    A->>CH: read analytics (for example the operations log)
    A-->>B: JSON
    B->>C: POST, PUT, PATCH, or DELETE /api/...
    C->>A: same path
    A->>PG: write
    A->>I: publish the event or operations log row
    A-->>B: JSON
```

- The UI is static files. Caddy fills in `index.html` as a template, so the
  UI knows the API URL (`VITE_API_URL`) at run time.
- The UI sends the access token in the `Authorization` header. It sends the
  refresh request with cookies (`credentials: 'include'`).
- For an organization-scoped route, imbi-api uses the role of the user in
  that organization. See [Security](security.md).
- A write never goes to ClickHouse directly. The row goes to Iggy, and
  iggy-connect writes it to ClickHouse later. A read just after a write can
  miss the new row. See [Events and analytics](events.md).

## Webhook

```mermaid
sequenceDiagram
    autonumber
    participant S as Sender (for example GitHub)
    participant C as Caddy
    participant G as imbi-gateway
    participant PG as Postgres (graph)
    participant I as Iggy
    participant P as Plugin action
    participant A as imbi-api
    S->>C: POST /gateway/notifications/{webhook_id}
    C->>G: POST /notifications/{webhook_id} (prefix removed)
    G->>PG: load the Webhook, its Organization, Integration, and rules
    G->>G: verify the signature (GitHub)
    G->>PG: find the projects from the identifier selector
    G->>I: publish the delivery to the events stream
    G->>G: evaluate the filter expression of each rule
    loop each matching rule, in rule order, for each project
        G->>P: run the action
        P->>A: call the API with the gateway token (for some actions)
    end
    G->>I: publish the outcome of each action
    G-->>S: 202 (an action ran) or 204 (nothing to do)
```

- The webhook URL contains the webhook id. The gateway finds the webhook,
  its organization, and its rules from that id.
- The gateway records each delivery, also when no rule matches. It runs
  actions only when the integration has the webhook-actions capability
  turned on.
- Rules run in the order of their `ordinal`. The order is important: for
  example, `add_deployment_event` needs the release that `create_release`
  makes.
- Actions such as `create_release` call imbi-api as the gateway service
  account, with `IMBI_GATEWAY_API_TOKEN`. Commit and pull request sync
  actions publish to Iggy directly.
- See [Gateway](../gateway/index.md) and
  [Webhook filter expressions](../gateway/webhook-filter-expressions.md).

## Scheduled task

```mermaid
sequenceDiagram
    autonumber
    participant SC as imbi-scheduler
    participant PG as Postgres (scheduler schema)
    participant A as imbi-api
    participant G as imbi-gateway
    participant I as Iggy
    SC->>PG: claim due tasks (FOR UPDATE SKIP LOCKED), move next_run_at
    SC->>I: publish the run row (running)
    alt api target
        SC->>A: get a token with the scheduler client credential
        SC->>A: one HTTP call to the target path
        A-->>SC: response
    else gateway target
        SC->>G: one HTTP call, with no token
        G-->>SC: response
    end
    SC->>I: publish the run row (terminal state)
```

- One replica claims each occurrence. More than one replica is safe.
- An `api` target runs as the `imbi-scheduler` service account. If the
  scheduler cannot get a token, the run is `skipped`, not `failed`.
- The scheduler starts work. It does not do the work. Long work (a
  maintenance operation, a workflow run) runs in the service that the call
  reaches.
- See [Scheduler](../scheduler/index.md).

## Workflow run

```mermaid
sequenceDiagram
    autonumber
    participant T as Trigger
    participant A as imbi-api
    participant PG as Postgres (workflow_runtime)
    participant W as imbi-workflows
    participant H as imbi-harness runner
    participant I as Iggy
    T->>A: start a run (UI or API, scheduler task, or gateway rule)
    A->>PG: create the run, then NOTIFY
    W->>PG: claim the run (FOR UPDATE SKIP LOCKED, with a lease)
    loop one step at a time
        alt deploy or rollback step
            W->>A: deploy as the imbi-workflows service account
            W->>A: poll the deployment until it ends
        else agent step
            W->>A: create the agent task of the step
            H->>A: claim the task (the runner connects out)
            H->>A: report the outcome
            W->>A: poll the task until it has an outcome
        else email step
            W->>A: send the email of the step
        else wait or decision step
            W->>W: wait, or ask the model and select a branch
        end
    end
    W->>I: publish the run and its events
```

- There are three triggers. A manual start comes from the UI or the API.
  A schedule trigger is the imbi-scheduler task `workflow-<binding id>`,
  which posts to the run endpoint as the scheduler service account. A
  webhook trigger is a `start_workflow` rule on a gateway webhook.
- imbi-workflows keeps the scheduler tasks and gateway rules in step with
  the trigger bindings that imbi-api writes (the trigger reconciler).
- imbi-api notifies imbi-workflows with Postgres `NOTIFY`. The workers also
  poll, so a lost notification adds delay only.
- The engine runs the steps of one run one at a time.
- If imbi-workflows cannot publish the history, an imbi-api sweep publishes
  it later.
- See [Workflows](../admin/workflows.md),
  [Agent runtime](agent-runtime.md), and
  [ADR 0021](../api/adr/0021-workflow-contract.md).
