# imbi-plugin-grafana

The Grafana plugin for the [Imbi](https://github.com/AWeber-Imbi)
platform, distributed as a single Python package (`imbi.plugins.grafana`)
exposing one Integration (`grafana`) with three capabilities:

- **`lifecycle`** — writes the project's `EXISTS_IN` edge, whose
  identifier (`{slug}-{id}` by default) the project's alert rules
  carry in a label (`service` by default), and a project link to the
  alert rules list searched by that label. The link key is the
  integration slug. Removes both on delete.
- **`webhook-actions`** — receives deliveries from a Grafana Alerting
  webhook contact point. imbi-gateway verifies the signature, finds the
  project by the label value, and records each delivery as an event.
  The capability advertises no custom actions.
- **`analysis`** — Project Doctor checks that the edge and link exist
  and match the integration options, with a one-click repair.

Options: `service_url` (the Grafana URL, required) and `label` (the
alert rule label that names the project, default `service`).

The Imbi host discovers the package by scanning `imbi.plugins.*` and
reads the module-level `PLUGIN` attribute; there are no entry points.
All plugin base classes come from `imbi.common.plugins`.

## The delivery

A Grafana webhook contact point sends its default JSON payload, one
request for each notification group:

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

## Signature

Turn on **HMAC signature** on the contact point. Grafana then sends the
hex HMAC-SHA256 of the raw body, keyed by the shared secret, in the
`X-Grafana-Alerting-Signature` header. Put the same secret in the
**Secret** field of the Imbi webhook. Leave the contact point's
**Timestamp Header** empty: with it set, Grafana signs
`<timestamp>:<body>` instead, which the gateway does not compute. The
gateway drops a delivery whose signature is missing or does not match.
The header name and prefix are the `SIGNATURE_HEADER` and
`SIGNATURE_PREFIX` constants in `imbi.plugins.grafana.plugin`.

## Development

```bash
moon run root:setup     # uv sync + pre-commit hooks
moon run grafana:test   # coverage (fails under 85%)
moon run grafana:lint grafana:typecheck grafana:format   # ruff + basedpyright + format check
```

Only the workflow steps call Grafana. They need the optional
`api_token` credential (a service account token with the `Viewer`
role) and send requests only to `service_url`. They use these Grafana
APIs:

- `GET /api/datasources` and `POST /api/ds/query`:
  <https://grafana.com/docs/grafana/latest/developers/http_api/data_source/>
- The Prometheus query fields (`expr`, `range`, `instant`):
  <https://grafana.com/docs/grafana/latest/datasources/prometheus/query-editor/>
  and
  <https://grafana.github.io/grafana-foundation-sdk/typescript/Reference/prometheus/object-dataquery>

## License

BSD-3-Clause.
