# Grafana

The `grafana` plugin receives deliveries from a Grafana Alerting webhook
contact point. imbi-gateway verifies the signature of each delivery,
finds the project that the notification is about, and records the
delivery as an event. You can then add webhook rules that act on the
events, for example start a workflow.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `webhook-actions` | Webhook actions | On | Project-scoped. Has no actions |

## Configuration

The plugin has no options and no credentials. It only receives.

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
    | Identifier Selector | The JSON Pointer to the value that names the project, for example `/commonLabels/service` or `/alerts/0/labels/service` |
    | User Subject Selector | Leave empty. Grafana sends no user |
    | Event Type Selector | `/status` |

3. Link each project to the identifier in **Project settings >
   Integrations**, or let the identifier selector point at a value that
   already matches the project identifier in this integration.
4. In Grafana, set the contact point URL to the webhook URL from Imbi, and
   route the alert rules that you want to send to the contact point.

The event type of a recorded delivery is the group status, `firing` or
`resolved`. A webhook rule filter can read the body under `payload`, for
example `payload.status == "firing"` or
`payload.alerts[0].labels.alertname == "5xx rate high"`.

## Webhook actions

None. The capability has no actions. imbi-gateway records Grafana
deliveries as events.

## Known limits

- The signature header and scheme are fixed in the plugin. A contact
  point with a changed **Header** or a set **Timestamp Header** is not
  verified, and its deliveries are dropped when the webhook has a secret.
- The gateway does not use `groupKey` as an idempotency key. A repeat
  notification of the same group is recorded as a second event.
- One delivery can carry many alerts. The identifier selector reads one
  value, so group the alert rules by the label that names the project.
