# Webhooks

A webhook is an inbound endpoint. An external system, for example GitHub,
PagerDuty, or SonarQube, sends HTTP POST deliveries to it. The
[gateway](../gateway/index.md) (imbi-gateway) receives each delivery,
finds the project, records the delivery, and runs the rules of the
webhook.

To manage webhooks, open **Admin > &lt;Org&gt; Admin > Webhooks**. The
**Admin** item shows only for platform administrators. The page has two
tabs:

| Tab | What it shows |
|---|---|
| **Endpoints** | The webhooks of the organization |
| **Delivery history** | The deliveries that the gateway recorded |

Each webhook belongs to one organization.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py webhook: admin:events:read -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `webhook:create` | Create webhooks | `admin` |
| `webhook:read` | View webhooks | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `webhook:update` | Update webhooks | `admin`, `developer` |
| `webhook:delete` | Delete webhooks | `admin` |
| `admin:events:read` | List events across every organization (audit / support) | `admin` |

<!-- END GENERATED -->

The **Delivery history** tab needs `admin:events:read`.

## The webhook URL

Imbi makes the id of a webhook when you create it. The **Notification
Path** of the webhook is `/<id>`. The full URL is:

```text
https://<imbi host>/gateway/notifications/<id>
```

Put this URL in the webhook settings of the external system. The id and
the path do not change.

## Create a webhook

1. Open **Admin > &lt;Org&gt; Admin > Webhooks**.
2. Click **New Webhook**.
3. Enter the fields in the tables below.
4. Add one or more rules. See [Rules](#rules).
5. Click **Create Webhook**.

| Field | What to enter |
|---|---|
| Name | Required. Imbi makes the slug from the integration slug and the name |
| Secret | The shared secret that the external system uses to sign deliveries. See [Secrets](#secrets) |
| Description | Optional |
| Icon | Optional |
| Integration | The [integration](integrations-and-plugins.md) that sends the deliveries |

The fields below are available when you select an integration:

| Field | What to enter |
|---|---|
| Identifier Selector (JSON Pointer) | Where the project identifier is in the body, for example `/repository/id`. Imbi finds the project whose identifier in this integration has this value |
| User Subject Selector (JSON Pointer) | Where the external user id is in the body, for example `/deployment/creator/id`. Imbi uses it to find the Imbi user who did the action |
| User Type Selector (JSON Pointer) | Where the sender type is, for example `/sender/type`. When the value is `Bot`, Imbi does not look up a user |
| Identity Integration Slug | Optional. The identity plugin that finds the user. Empty: the identity plugins of the integration |
| Event Type Selector | The event type of the delivery. A value that starts with `/` is a JSON Pointer into the body. Any other value is an HTTP header name, for example `x-github-event`. When the header is not there, Imbi uses the value itself as the event type |

In this release, the gateway processes only webhooks that have an
integration. It accepts a delivery to a webhook without an integration,
logs a warning, and does nothing more.

When you edit a webhook, the form also shows the **ID**, the
**Notification Path**, and the **Slug**. If you change the integration,
Imbi makes a new slug.

## How the gateway processes a delivery

1. The gateway finds the webhook from the id in the URL.
2. For a GitHub integration, the gateway checks the signature. See
   [Secrets](#secrets).
3. The gateway reads the project identifier with the **Identifier
   Selector** and finds the project. When no project matches, it stops.
4. The gateway records the delivery as an event. The event goes to the
   Iggy `events` stream and then to the ClickHouse `events` table. The
   **Delivery history** tab and the project activity feed show it.
5. If the **Webhook actions** capability of the integration is off, the
   gateway stops here.
6. The gateway runs every rule whose filter matches, in the order of the
   rules.

## Rules

A rule has three parts:

| Field | What to enter |
|---|---|
| Filter Expression (CEL) | Required. A CEL expression. The rule runs when it is true. For example `type == "push"` or `payload.action == "opened"` |
| Handler | Required. The action to run, in the form `<plugin slug>#<action name>`, for example `gateway-actions#create_release` |
| Handler Config (JSON) | The configuration of the action. Each action has its own fields |

The filter sees the body under `payload`, not at the top level. For the
variables and the examples, see
[Webhook Rule Filter Expressions](../gateway/webhook-filter-expressions.md).
For the actions and their configuration, see
[Gateway](../gateway/index.md).

Use the arrows on a rule to change the order. Order is important for the
release actions: `create_release` must run before `add_deployment_event`.

Imbi does not check the handler when you save. Make sure that each
handler has the form `<plugin slug>#<action name>`. If one rule of a
webhook has a handler in another form, the gateway drops every delivery
to that webhook. If the plugin or the action does not exist, the gateway
skips that rule only.

### Workflow rules

A rule with the handler `gateway-actions#start_workflow` starts a
[workflow](workflows.md). Imbi writes these rules when you activate a
workflow with a webhook trigger. Only the `imbi-workflows` service account
can add, change, or remove them. If you change one, Imbi refuses the save
with `403 workflow_rule_forbidden`. You can still change the other rules
of the webhook.

## Secrets

Imbi encrypts the secret before it stores it. The API never returns the
secret. When you edit a webhook, leave **Secret** empty to keep the
current secret.

How the gateway uses a secret:

| Source | Header | Behavior |
|---|---|---|
| The webhook secret, for a GitHub integration | `X-Hub-Signature-256` | With a secret, the gateway drops a delivery whose signature is missing or wrong. Without a secret, it processes the delivery as unverified and logs a warning one time |
| A per-project secret that a plugin stores when it creates the remote webhook (PagerDuty) | `X-PagerDuty-Signature` | The gateway drops a delivery whose signature does not match |

The `create_agent_task` and `start_workflow` actions run only for a
verified delivery. Set a secret on each webhook that uses them.

The gateway replaces the values of the signature headers with
`[redacted]` before it records the delivery.

## Who owns the rules

Imbi records the person who created the webhook or saved it last, as
`created_by`. Each save replaces it. That person is responsible for what
the rules do: an agent task that a rule makes belongs to them.

When `created_by` is not a person who can create agent tasks in the
organization, Imbi refuses the task. To fix it, a person who can create
agent tasks opens the webhook and saves it. See
[Agent tasks](agent-tasks.md).

## Delivery history

The **Delivery history** tab lists the recorded deliveries, newest first.
Use the filters to narrow the list:

| Filter | Values |
|---|---|
| Integration | All integrations, or one |
| Event type | Text, for example `pull_request` |
| Project | All projects, or one |
| Time range | Last 24 hours, Last 7 days (default), Last 30 days, All time |

The list reads the events of every organization, not only the
organization that you select.

Each row shows the result of the handlers:

| Result | Meaning |
|---|---|
| Recorded · no handlers | The gateway recorded the delivery and ran no handler |
| `N` handlers · ok | Every handler that ran succeeded |
| `N` of `M` handlers ok | Some handlers failed or were skipped. Open the row for the error |

## Delete a webhook

Click the delete action in the list. The external system then gets no
error from the gateway, but the gateway does nothing with the deliveries.

## Related pages

- [Gateway](../gateway/index.md)
- [Webhook Rule Filter Expressions](../gateway/webhook-filter-expressions.md)
- [Integrations and Plugins](integrations-and-plugins.md)
- [Agent tasks](agent-tasks.md)
- [Workflows](workflows.md)
