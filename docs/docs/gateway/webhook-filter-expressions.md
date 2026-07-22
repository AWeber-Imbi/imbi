# Webhook Rule Filter Expressions

Each `WebhookRule` carries a `filter_expression` written in
[CEL](https://github.com/google/cel-spec) (Common Expression Language). When
a webhook is delivered, the gateway evaluates every rule's expression and runs
the rule's handler only when the expression is truthy. If no rule matches, the
delivery is recorded but no handler runs.

## Evaluation context

The expression is evaluated against the same data the gateway materializes
into the activity-feed `events` row (`imbi_common.models.Event`). The
project-independent fields of that row are exposed as top-level variables:

| Variable | Type | Contents |
|---|---|---|
| `type` | string | Resolved event type — the value selected by the service's `event_type_selector` (e.g. the `X-GitHub-Event` header value). `''` when no selector is configured. |
| `third_party_service` | string | The service slug (e.g. `github`). |
| `attributed_to` | string | The resolved Imbi user; `''` when the delivery maps to no user. |
| `metadata.headers` | map | The request headers, **keys lower-cased**, sensitive values redacted (see below). |
| `payload` | map | The webhook request body, exactly as received. |

> **Note:** the webhook body is under `payload`, not at the top level. A
> filter on a body field is `payload.action == "opened"`, not
> `action == "opened"`.

## Examples

```cel
// Match on the X-GitHub-Event header
metadata.headers["x-github-event"] == "push"

// Same, via the resolved event type (requires event_type_selector:
// X-GitHub-Event on the service)
type == "push"

// Match on a body field
payload.action == "opened"

// Combine
type == "deployment_status" && payload.deployment_status.state == "success"
```

Header names in `metadata.headers` are lower-cased, so always index with the
lower-case form (`metadata.headers["x-github-event"]`).

## Action handler_config uses the same shape

Action `handler_config` CEL expressions (`committish_expression`,
`version_expression`) and JSON-Pointer selectors (`title_selector`,
`status_selector`, …) resolve against this **same** event context. So the
webhook body is under `/payload` for pointers and `payload.<field>` for CEL —
identical to a rule's `filter_expression`. For example, a body field is
`payload.deployment.sha` in both a filter and a `committish_expression`, and a
selector reads `/payload/deployment/ref`.

## Redacted headers

Headers that may carry credentials or webhook signatures are replaced with
`[redacted]` before they reach both ClickHouse and the filter context. You
cannot filter on the *value* of these headers (only on their presence):

`authorization`, `cookie`, `set-cookie`, `proxy-authorization`,
`x-hub-signature`, `x-hub-signature-256`, `x-gitlab-token`,
`x-pagerduty-signature`, `x-sonar-webhook-hmac-sha256`.

## Available functions

In addition to the [CEL standard
functions](https://github.com/google/cel-spec/blob/master/doc/langdef.md#standard-definitions),
expression evaluation uses [`cel-python`](https://pypi.org/project/cel-python/).
A failed or non-boolean evaluation logs a warning and is treated as
non-matching for that rule (it never raises into the request).
