# imbi-plugin-posthog

The PostHog plugin for the [Imbi](https://github.com/AWeber-Imbi)
platform, distributed as a single Python package (`imbi.plugins.posthog`)
exposing one Integration (`posthog`) with one capability:

- **`webhook-actions`** — receives deliveries from a PostHog webhook
  destination. imbi-gateway verifies the signature, finds the project,
  and records each delivery as an event. The capability advertises no
  custom actions.

The Imbi host discovers the package by scanning `imbi.plugins.*` and
reads the module-level `PLUGIN` attribute; there are no entry points.
All plugin base classes come from `imbi.common.plugins`.

## The delivery

Configure the PostHog webhook destination with this JSON body:

```json
{
  "event": "{event}",
  "person": "{person}"
}
```

PostHog expands `{event}` and `{person}` to objects, so a delivery is:

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
The header name and prefix are the `SIGNATURE_HEADER` and
`SIGNATURE_PREFIX` constants in `imbi.plugins.posthog.plugin`.

## Development

```bash
moon run root:setup     # uv sync + pre-commit hooks
moon run posthog:test   # coverage (fails under 85%)
moon run posthog:lint posthog:typecheck posthog:format   # ruff + basedpyright + format check
```

The plugin needs no credentials (`auth_type='none'`): it only receives.

## License

BSD-3-Clause.
