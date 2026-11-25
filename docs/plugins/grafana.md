# Grafana

The `grafana` plugin links each project to the Grafana alert rules that
carry its slug in a label, and receives deliveries from a Grafana
Alerting webhook contact point. imbi-gateway verifies the signature of
each delivery, finds the project by that label, and records the delivery
as an event. You can then add webhook rules that act on the events, for
example start a workflow.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `lifecycle` | Project lifecycle | On | Project-scoped. Events: `created`, `updated`, `deleted`. Supports lifecycle sync |
| `webhook-actions` | Webhook actions | On | Project-scoped. Has no actions |
| `analysis` | Project doctor | On | Project-scoped |
| `workflow-steps` | Workflow steps | On | Organization. See [Workflow steps](#workflow-steps) |

## Configuration

Only the workflow steps call Grafana. The other capabilities use no
credential.

| Option | Required | Default | What it is |
|---|---|---|---|
| Grafana URL (`service_url`) | Yes | | Base URL of Grafana, for example `https://grafana.example.com`. Used for the alert rules link of each project |
| Project label (`label`) | No | `service` | The alert rule label that names the project |

| Credential | Required | What it is |
|---|---|---|
| Service Account Token (`api_token`) | No | A Grafana service account token with the `Viewer` role. The workflow steps need it |

## How a project is linked

Grafana has no project resource. The link is a convention: every alert
rule of a project carries the **Project label** with the project's
identifier, which is `{slug}-{id}` (for example `webform-V1StGXR8_Z5jdHi6B-myT`;
slugs are not unique) unless an edge already exists
with another value. The lifecycle capability writes that identifier to
the project's `EXISTS_IN` edge and sets the `grafana` project link to
the alert rules list searched by `label:<label>=<identifier>`. The
gateway matches the identifier against the value that the webhook's
Identifier Selector reads from each delivery.

- **Created, updated, sync**: write the edge and the link. A project
  that already has them is left as is.
- **Deleted**: remove the edge and the link.
- **Archived**: nothing. Grafana has no archive concept.

In Grafana, add the label to each alert rule of the project, for
example `service=webform-V1StGXR8_Z5jdHi6B-myT`, and group the notification policy by that
label so each delivery carries one value.

## Doctor checks

| Slug | Status | What it means | Fix |
|---|---|---|---|
| `exists-in` | `pass` | The edge and the `grafana` link match the integration options | |
| `exists-in` | `fail` | The project has no edge, so the gateway cannot route deliveries to it | **Link the project to Grafana** writes the edge and the link |
| `exists-in` | `warn` | The edge is not verified, or the edge or the link does not match the options | **Link the project to Grafana** refreshes them |
| `identifier` | `pass` | The identifier is `{slug}-{id}` | |
| `identifier` | `warn` | The identifier differs from `{slug}-{id}`, for example after a rename or a manual edit. The old value still works | **Use the current project value as the identifier** rewrites the edge. Update the labels in Grafana first: alert rules labelled with the old value stop matching |

The doctor cannot confirm that alert rules with the label exist, because
the doctor does not call Grafana. Neither fix is sweepable.

## The delivery

In Grafana, make a webhook contact point (**Alerting > Contact points >
New contact point > Webhook**). Keep the default payload. Grafana sends
one request for each notification group:

```json
{
  "receiver": "imbi",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {"alertname": "5xx rate high", "service": "webform"},
      "annotations": {"runbook_url": "https://imbi.example.com/..."},
      "startsAt": "...",
      "endsAt": "0001-01-01T00:00:00Z",
      "values": {"B": 12.5},
      "generatorURL": "...",
      "fingerprint": "...",
      "silenceURL": "..."
    }
  ],
  "groupLabels": {},
  "commonLabels": {},
  "commonAnnotations": {},
  "externalURL": "https://grafana.example.com/",
  "groupKey": "...",
  "title": "...",
  "state": "alerting",
  "message": "..."
}
```

`status` is `firing` or `resolved` for the group. Each alert has its own
`status`, `labels`, and `annotations`.

## Signature

Under the contact point's **Optional settings**, turn on **HMAC
signature** and set these values:

| Field | Value |
|---|---|
| Secret | A shared secret. Put the same value in the **Secret** field of the Imbi webhook |
| Header | `X-Grafana-Alerting-Signature` (the default) |
| Timestamp Header | Leave empty |

Grafana sends the hex HMAC-SHA256 of the raw body, keyed by the secret,
in the signature header. The gateway drops a delivery whose signature is
missing or does not match.

Leave **Timestamp Header** empty. With it set, Grafana signs
`<timestamp>:<body>` instead of the body, and the gateway does not
compute that.

## Webhook

To set up the webhook:

1. In Imbi, enable the `grafana` plugin and make an integration of it. See
   [Integrations and Plugins](../admin/integrations-and-plugins.md).
2. Make a webhook for the integration (see
   [Webhooks](../admin/webhooks.md)). Set these values:

    | Field | Value |
    |---|---|
    | Secret | The secret you entered on the Grafana contact point |
    | Identifier Selector | The JSON Pointer to the label value that names the project: `/commonLabels/<label>`, for example `/commonLabels/service`, when the notification policy groups by the label; otherwise `/alerts/0/labels/<label>` |
    | User Subject Selector | Leave empty. Grafana sends no user |
    | Event Type Selector | `/status` |

3. Assign the `lifecycle` capability to the project types that have
   alert rules. New projects get their edge on creation. For existing
   projects, run **Sync lifecycle** on the integration, or use the
   Doctor fix on each project.
4. In Grafana, set the contact point URL to the webhook URL from Imbi, and
   route the alert rules that you want to send to the contact point.

The event type of a recorded delivery is the group status, `firing` or
`resolved`. A webhook rule filter can read the body under `payload`, for
example `payload.status == "firing"` or
`payload.alerts[0].labels.alertname == "5xx rate high"`.

## Webhook actions

None. The capability has no actions. imbi-gateway records Grafana
deliveries as events.

## Workflow steps

The workflow steps read Prometheus metrics through a Grafana data
source. They need the `api_token` credential. They send requests only
to the **Grafana URL** of the integration.

| Type | Kind | What it does |
|---|---|---|
| `grafana.gather_metrics` | Action | Runs a PromQL range query from `start` (default `now-1h`) to `end` (default `now`), with a step of `step_seconds` (default 60). The output has up to 50 series of up to 500 points, a `summary` with the min, max, and last value of each series, and `truncated` |
| `grafana.metric_threshold` | Gate | Runs an instant PromQL query that gives one value. When `value <operator> threshold` is true (`lt`, `lte`, `gt`, or `gte`), it takes the `Pass` port. Otherwise it polls each 60 seconds. After 30 minutes it takes the `Failed` port |

The **Data source** field lists the Prometheus data sources of Grafana.
For the gate, reduce the query to one series, for example with `sum()`
or `max()`. A query that gives more than one series fails the step. A
query that gives no value, or `NaN`, polls again.

See [Workflow Steps Capability](../common/plugins/workflow-steps.md).

## Known limits

- The signature header and scheme are fixed in the plugin. A contact
  point with a changed **Header** or a set **Timestamp Header** is not
  verified, and its deliveries are dropped when the webhook has a secret.
- The gateway does not use `groupKey` as an idempotency key. A repeat
  notification of the same group is recorded as a second event.
- One delivery can carry many alerts. The identifier selector reads one
  value, so group the notification policy by the label that names the
  project.
- The plugin cannot create alert rules, add the label to them, or
  confirm that labelled rules exist.
