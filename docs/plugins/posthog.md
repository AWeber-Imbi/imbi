# PostHog

The `posthog` plugin receives deliveries from a PostHog webhook
destination. imbi-gateway verifies the signature of each delivery, finds
the project that the event is about, and records the delivery as an
event. You can then add webhook rules that act on the events, for example
start a workflow.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `webhook-actions` | Webhook actions | On | Project-scoped. Has no actions |

## Configuration

The plugin has no options and no credentials. It only receives.

## The delivery

In PostHog, make a webhook destination (**Data pipelines > Destinations >
Webhook**). Set the JSON body to:

```json
{
  "event": "{event}",
  "person": "{person}"
}
```

PostHog expands `{event}` and `{person}` to objects. A delivery looks like
this:

```json
{
  "event": {
    "uuid": "...",
    "event": "$pageview",
    "distinct_id": "...",
    "properties": {},
    "timestamp": "...",
    "url": "https://us.posthog.com/project/1/events/..."
  },
  "person": {
    "id": "...",
    "name": "...",
    "url": "https://us.posthog.com/project/1/person/...",
    "properties": {}
  }
}
```

## Signature

PostHog signs each request per the
[Standard Webhooks](https://www.standardwebhooks.com/) specification. The
destination sends three headers:

| Header | Value |
|---|---|
| `Webhook-Id` | The unique id of the message |
| `Webhook-Timestamp` | The send time, as integer seconds since the epoch |
| `Webhook-Signature` | Space-separated `v1,<base64>` tokens |

Each token is the base64 HMAC-SHA256 of
`<webhook-id>.<webhook-timestamp>.<body>`, keyed by the signing secret.
Put the secret that PostHog shows for the destination (`whsec_...`) in
the **Secret** field of the Imbi webhook; the `whsec_` prefix is
optional. The gateway drops a delivery whose signature is missing or does
not match, and a delivery whose timestamp is more than five minutes from
the gateway clock.

## Webhook

To set up the webhook:

1. In Imbi, enable the `posthog` plugin and make an integration of it. See
   [Integrations and Plugins](../admin/integrations-and-plugins.md).
2. Make a webhook for the integration (see
   [Webhooks](../admin/webhooks.md)). Set these values:

    | Field | Value |
    |---|---|
    | Secret | The secret that the PostHog destination signs with |
    | Identifier Selector | The JSON Pointer to the event property that names the project, for example `/event/properties/service` |
    | User Subject Selector | Optional. For example `/person/properties/email` |
    | Event Type Selector | `/event/event` |

3. Link each project to the identifier in **Project settings > Services**,
   or let the identifier selector point at a value that already matches
   the project identifier in this integration.
4. In PostHog, set the destination URL to the webhook URL from Imbi, and
   add the filters for the events that you want to send.

The event type of a recorded delivery is the PostHog event name, for
example `$pageview`. A webhook rule filter can read the body under
`payload`, for example `payload.event.event == "signup"`.

## Webhook actions

None. The capability has no actions. imbi-gateway records PostHog
deliveries as events.

## Known limits

- The signature header, prefix, and scheme are fixed in the plugin. A
  destination that does not sign per Standard Webhooks is not verified,
  and its deliveries are dropped when the webhook has a secret.
- The gateway does not use `Webhook-Id` as an idempotency key. A
  redelivery is recorded as a second event.
