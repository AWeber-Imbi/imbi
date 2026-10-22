# Gateway

`imbi-gateway` receives webhooks from external systems, for example GitHub,
PagerDuty, and SonarQube. For each delivery, it finds the Imbi projects that
the delivery is about, records the delivery, and runs the rules of the
webhook. A rule calls an **action**, for example "create a release" or
"start an agent task".

The gateway runs on port 8003. The all-in-one image serves it under
`/gateway`.

## The webhook URL

Each Webhook has its own URL:

```text
POST https://<imbi host>/gateway/notifications/<webhook id>
```

The **Notification Path** on the webhook detail page shows `/<webhook id>`.
The endpoint has no bearer check. To prove that a delivery is genuine, use a
signing secret (see [Signature verification](#signature-verification)).

The body must be JSON.

## Status codes

| Code | Meaning |
|---|---|
| `202 Accepted` | One or more rules matched, and the gateway ran their actions. An action that fails does not change the code. The webhook history shows the result of each action |
| `204 No Content` | The gateway accepted the delivery and did nothing. See the list below |
| `422 Unprocessable Content` | The body is not JSON |
| `500 Internal Server Error` | The webhook belongs to more than one organization |

The gateway returns `204` when one of these is true:

- No webhook has this id.
- The webhook has no integration.
- The signature is missing or does not verify.
- The **Identifier Selector** does not resolve in the body.
- No project has that identifier for the integration.
- The `webhook-actions` capability of the integration is off. The gateway
  records the delivery, but runs no rule.
- No rule matches.

A scheduled task with a `gateway` target records `204` as `no_effect`. See
[Scheduled Tasks](../scheduler/tasks.md#gateway).

## How the gateway processes a delivery

1. It reads the Webhook, its organization, its integration, and its rules.
2. For a GitHub integration, it verifies the signature when the webhook has
   a secret.
3. It reads the project identifier from the body with the **Identifier
   Selector**.
4. It finds each project whose identifier for the integration has that
   value. More than one project can match. For PagerDuty, it verifies the
   signature against the secret of each matched project.
5. It finds the Imbi user who caused the event, when it can (see
   [Attribution](#attribution)).
6. It resolves the event type with the **Event Type Selector**.
7. It records one `events` row for each matched project. The row goes to
   the Iggy stream `events`, topic `gateway`, and the sink writes it to the
   ClickHouse `events` table.
8. It evaluates the filter expression of each rule. See
   [Webhook Rule Filter Expressions](webhook-filter-expressions.md).
9. For each matched project, it runs each matched rule in rule order.
10. It records the outcome of each action (`succeeded`, `failed`, or
    `skipped`) on the `events` row.

The **Webhook History** of a webhook shows these rows.

## Set up a webhook

Do these steps one time for each source.

1. Make sure that the integration has the `webhook-actions` capability on.
   See [Integrations and Plugins](../admin/integrations-and-plugins.md).
2. Make sure that each project has its identifier for the integration, for
   example the GitHub repository id.
3. Open **Admin > \<organization\> Admin > Webhooks** and create a webhook.
   See [Webhooks](../admin/webhooks.md) for the form.
4. Set the fields of the integration binding:

    | Field | What to enter |
    |---|---|
    | Integration | The integration that sends the webhook |
    | Identifier Selector | A JSON pointer into the **body**, for example `/repository/id` |
    | User Subject Selector | A JSON pointer to the id of the external user, for example `/sender/id` |
    | User Type Selector | Optional. A JSON pointer to the account type, for example `/sender/type`. A value of `Bot` skips the user lookup |
    | Identity Integration Slug | Optional. The integration that maps the external user to an Imbi user |
    | Event Type Selector | Optional. A header name, for example `x-github-event`, or a JSON pointer that starts with `/` |
    | Secret | The signing secret. For GitHub, use the secret of the GitHub hook |

5. Add the rules. Each rule has a **Filter Expression (CEL)**, a
   **Handler**, and a **Handler Config (JSON)**. Rules run in the order of
   the list.
6. Save the webhook. Copy its URL into the source system.

The selectors of the binding read the body directly (`/repository/id`). The
selectors in a `handler_config` read the event context, so the body is
under `/payload` (`/payload/repository/id`).

The person who saves the rules is accountable for them. An agent task that a
rule makes belongs to that person.

## Signature verification

| Source | Header | Secret | Prefix |
|---|---|---|---|
| GitHub | `X-Hub-Signature-256` | The **Secret** of the webhook | `sha256=` |
| PagerDuty | `X-PagerDuty-Signature` | The secret on the identifier of the project | `v1=` |

The signature is an HMAC-SHA256 of the raw body. The header can hold more
than one signature, separated by commas. One match is sufficient.

- When a secret is set, a delivery with a missing or wrong signature gets
  `204`, and the gateway records nothing.
- When a GitHub webhook has no secret, the gateway processes its deliveries
  without verification. It logs a warning one time for each webhook.

The filter variable `github_signature_verified` is `true` only for a GitHub
delivery that verified. The actions `create_agent_task` and `start_workflow`
run only for a signed delivery: a GitHub delivery that verified, or a
delivery to a project whose identifier has a secret.

## Attribution

The gateway reads the external user id with the **User Subject Selector**.
It then asks imbi-api for the Imbi user with that identity. It asks the
**Identity Integration Slug** when you set it. Otherwise it asks the
webhook's own integration, when that integration has the `identity`
capability on.

The resolved user goes into `attributed_to`, and into `created_by` of a
release that an action makes. When the gateway finds no user, or two
different users, it leaves the delivery unattributed.

## Handlers

A rule's **Handler** has the form `<plugin slug>#<action name>`, for
example `gateway-actions#create_release`. The plugin slug and the action
name use lowercase letters, digits, and hyphens or underscores.

imbi-api checks the handler when you save the rule. It refuses a handler
in another form, and a plugin or action that is not in its plugin
registry. imbi-api does not load the `gateway-actions` plugin, so it
checks only the form of a `gateway-actions` handler.

The gateway resolves the handler again when a delivery arrives. When the
handler has another form, the plugin or the action does not exist, or the
`handler_config` is not valid, the gateway logs an error and skips that
rule. The other rules of the webhook still run.

When a plugin declares credentials, its actions get the credentials of the
webhook's integration. When the integration has no credentials, the gateway
skips the rule.

To write a new action, see
[Webhook Actions Capability](../common/plugins/webhook-actions.md).

## Built-in actions

The gateway includes the plugin `gateway-actions`. It needs no credentials.

| Handler | What it does |
|---|---|
| `gateway-actions#update_project` | Patches the project with values from the delivery |
| `gateway-actions#create_release` | Creates the release, or confirms that it exists |
| `gateway-actions#add_deployment_event` | Records a deployment status for an environment |
| `gateway-actions#publish_release` | Publishes the release on a successful deployment |
| `gateway-actions#block_release` | Blocks the release on a failed deployment |
| `gateway-actions#update_release_drift` | Sends a push of the drift notes ref to imbi-api |
| `gateway-actions#ingest_sbom` | Stores a CycloneDX SBOM on a release |
| `gateway-actions#create_agent_task` | Starts an agent task on the project |
| `gateway-actions#start_workflow` | Starts a workflow run |

In the tables below, a **pointer** is a JSON pointer into the event context,
and a **CEL** field is a CEL expression over the event context. The webhook
body is `/payload` in a pointer and `payload` in CEL. CEL fields in a
`handler_config` can use `substring()`. See
[Webhook Rule Filter Expressions](webhook-filter-expressions.md#available-functions).

### update_project

`handler_config` is a list. Each item adds one value to the project with a
JSON Patch `add` operation.

| Field | Type | Required | What it is |
|---|---|---|---|
| `path` | JSON pointer | Yes | The location on the Imbi project |
| `from` | pointer | Yes | The value to read from the delivery |

```json
[{"path": "/description", "from": "/payload/repository/description"}]
```

### create_release

| Field | Type | Default | What it is |
|---|---|---|---|
| `committish_expression` | CEL | none | The commit of the release, as 7 lowercase hex characters |
| `version_expression` | CEL | none | The tag of the release |
| `title_selector` | pointer | none | The title. When it is not set or is `null`, the title is `Release <tag>`, or `Release <commit>` when there is no tag |

You must set `committish_expression`, `version_expression`, or both. When
neither resolves, the action does nothing. imbi-api finds the commit of a
tag when you set only `version_expression`.

The create is idempotent. Two rules that announce the same release make one
release.

```json
{
  "committish_expression": "substring(payload.deployment.sha, 0, 7)",
  "version_expression": "payload.deployment.ref",
  "title_selector": "/payload/deployment/description"
}
```

### add_deployment_event

| Field | Type | Default | What it is |
|---|---|---|---|
| `environment_selector` | pointer | required | The environment slug |
| `committish_expression` | CEL | required | The commit of the deployment |
| `status_selector` | pointer | required | The deployment state. See [the state mapping](webhook-filter-expressions.md#deployment-states) |
| `version_expression` | CEL | none | The tag. The action finds the release by tag first, then by commit |
| `note_selector` | pointer | none | A note for the event |
| `external_run_id_selector` | pointer | none | The id of the external run. imbi-api uses it to update the event that the deploy flow already recorded |
| `external_run_url_selector` | pointer | none | The URL of the external run. A `null` or empty value is ignored |

When no release matches, the action records the deployment on the project
and environment without a release. The `deployment-sweep` maintenance
operation attaches the release later. A state that is not in the mapping is
skipped.

```json
{
  "environment_selector": "/payload/deployment/environment",
  "committish_expression": "substring(payload.deployment.sha, 0, 7)",
  "version_expression": "payload.deployment.ref",
  "status_selector": "/payload/deployment_status/state",
  "external_run_url_selector": "/payload/deployment_status/log_url"
}
```

### publish_release

| Field | Type | Default | What it is |
|---|---|---|---|
| `version_expression` | CEL | required | The tag of the release |
| `status_selector` | pointer | required | The deployment state |
| `prerelease` | boolean | `false` | Mark the remote release as a prerelease |

The action runs only when the state maps to `success`. It makes the remote
release for the tag, for example the GitHub Release. When imbi-api has no
release for the tag (`404`), or the release is blocked (`409`), the action
does nothing.

### block_release

| Field | Type | Default | What it is |
|---|---|---|---|
| `version_expression` | CEL | required | The tag of the release |
| `status_selector` | pointer | required | The deployment state |
| `reason_selector` | pointer | none | The reason. The default is `Deployment reported <state>`. Imbi keeps 500 characters |

The action runs only when the state maps to `failed` (`failure` or `error`).
The state `inactive` does not block a release.

### update_release_drift

| Field | Type | Default | What it is |
|---|---|---|---|
| `ref` | string | `refs/notes/imbi-drift` | The notes ref that carries the drift verdicts |

Use it with a GitHub `push` delivery. The action skips a push to any other
ref, and a push without a full `before` and `after` commit. It sends `before`
and `after` to imbi-api, which reads the changed notes and marks the
releases. See [Drift](../user-guide/drift.md).

### ingest_sbom

| Field | Type | Default | What it is |
|---|---|---|---|
| `version_expression` | CEL | required | The tag of the release |
| `sbom_selector` | pointer | `/payload` | The CycloneDX 1.7 document |
| `committish_expression` | CEL | none | When set, the action creates the release if no release has the tag. Imbi keeps the first 7 hex characters |
| `title_selector` | pointer | none | The title of a release that the action creates |

When no release has the tag and `committish_expression` is not set, the
action drops the SBOM and logs a warning.

```json
{
  "version_expression": "payload.ref_name == \"main\" ? substring(payload.sha, 0, 7) : payload.ref_name",
  "sbom_selector": "/payload/sbom",
  "committish_expression": "payload.sha"
}
```

### create_agent_task

| Field | Type | Default | What it is |
|---|---|---|---|
| `agent_slug` | string | required | The agent that does the task |
| `title_expression` | CEL | required | The title. For a fixed text, use a quoted CEL string |
| `description_expression` | CEL | required | The description |
| `delivery_id_selector` | pointer | `/metadata/headers/x-github-delivery` | The id of the delivery |

The action runs only for a signed delivery with a valid delivery id. A
redelivery makes no second task. See
[Agent Tasks](../admin/agent-tasks.md#webhooks).

### start_workflow

| Field | Type | Default | What it is |
|---|---|---|---|
| `workflow_slug` | string | required | The workflow |
| `trigger` | string | required | The webhook trigger of the workflow |
| `binding` | string | required | The id of the trigger binding |
| `delivery_id_selector` | pointer | `/metadata/headers/x-github-delivery` | The id of the delivery |

Do not write this rule. imbi-workflows writes it when you activate a
workflow with a webhook trigger. The action runs only for a signed delivery
with a valid delivery id. See [Workflows](../admin/workflows.md#triggers).

## Plugin actions

Other plugins add actions. These are the actions of the plugins in this
repository:

| Handler | What it does | `handler_config` |
|---|---|---|
| `github#sync_commits` | Gets the commits of a push and records them | Optional pointers: `before_selector`, `after_selector`, `ref_selector`, `repository_selector`, `repo_api_url_selector`. Optional `api_base_url` |
| `github#sync_tags` | Records the pushed tag | As `sync_commits`, without `before_selector`. Optional `reconcile_all` (default `false`) records all tags |
| `github#sync_pull_requests` | Records `pull_request` events | Optional pointers: `action_selector`, `pr_selector`, `repository_selector`, `repo_api_url_selector`. Optional `api_base_url` |
| `sonarqube#update_project_from_webhook` | Gets SonarQube measures and patches the project | A list of `{"metric": "coverage", "path": "/<project pointer>"}` |

The pointer defaults read the GitHub payload, for example
`/payload/repository/full_name`. For each plugin, see
[GitHub](../plugins/github.md) and [SonarQube](../plugins/sonarqube.md).

## Settings

The full list is in [Configuration](../api/configuration.md). The gateway
needs these:

| Variable | What it is |
|---|---|
| `POSTGRES_URL` | The graph, for webhooks, rules, integrations, and projects |
| `CLICKHOUSE_URL` | ClickHouse. The gateway does not start when it cannot connect |
| `IGGY_URL` | Iggy, for the `events` rows. The gateway does not start when it cannot connect |
| `IMBI_AUTH_ENCRYPTION_KEY` | Decrypts webhook secrets and integration credentials. Use the same value as imbi-api |
| `IMBI_GATEWAY_API_TOKEN` | The `ik_` API key of the `imbi-gateway` service account |
| `IMBI_INTERNAL_API_URL` | Where the gateway connects to imbi-api, for example `http://imbi-api:8000` |
| `IMBI_API_URL` | The public URL of imbi-api. The gateway uses its path, for example `/api`, as the route prefix. It must be an absolute URL |

### The service account

The actions call imbi-api as the `imbi-gateway` service account. Its role,
also `imbi-gateway`, grants `project:read`, `project:write`, `user:read`,
`agent_task:create`, and `workflow:run`.

- `imbi-api setup` makes the account and its API key. When
  `IMBI_GATEWAY_API_TOKEN` is set, setup uses that value. When it is not
  set, setup prints a new key one time.
- In the all-in-one image (`IMBI_SERVICE=all`), the entrypoint makes the key
  when the variable is not set.
- The account must be a member of each organization that has webhooks, with
  the `imbi-gateway` role. For another organization, run
  `imbi-api setup-service-accounts --organization <organization slug>`.

## Endpoints

| Path | What it is |
|---|---|
| `POST /notifications/{webhook_id}` | The webhook endpoint. Public as `/gateway/notifications/{webhook_id}` |
| `GET /status` | The health check. Public as `/gateway/status` |
| `GET /metrics` | Prometheus metrics. The proxy refuses `/gateway/metrics`, so scrape the pod |

The counter `imbi.gateway.deployment_events` counts the outcome of each
`add_deployment_event` call.
