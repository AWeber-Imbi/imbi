# Webhook Rule Filter Expressions

Each `WebhookRule` carries a `filter_expression` written in
[CEL](https://github.com/google/cel-spec) (Common Expression Language). When
a webhook is delivered, the gateway evaluates every rule's expression and runs
the rule's handler only when the expression is truthy. If no rule matches, the
delivery is recorded but no handler runs.

Recorded deliveries are published to the Iggy `events` stream, topic
`gateway`, and land in the ClickHouse `events` table through the sink.

## Evaluation context

The expression is evaluated against the same data the gateway materializes
into the activity-feed `events` row (`imbi.common.models.Event`). The
project-independent fields of that row are exposed as top-level variables:

| Variable | Type | Contents |
|---|---|---|
| `type` | string | Resolved event type — the value selected by the webhook's `event_type_selector` (e.g. the `X-GitHub-Event` header value). `''` when no selector is configured. When the selector names a header that is absent, the selector itself is the value. |
| `integration` | string | The Integration slug (e.g. `github`). |
| `attributed_to` | string | The resolved Imbi user; `''` when the delivery maps to no user. |
| `metadata.headers` | map | The request headers, **keys lower-cased**, sensitive values redacted (see below). |
| `payload` | map | The webhook request body, exactly as received. |
| `metadata.webhook_id` | string | The id of the webhook, from the request path. |
| `github_signature_verified` | bool | `true` only when the gateway verified the `X-Hub-Signature-256` header of a GitHub delivery against the webhook **Secret**. The sender cannot set it, because it is not in `payload`. It is not recorded on the `events` row. |

> **Note:** the webhook body is under `payload`, not at the top level. A
> filter on a body field is `payload.action == "opened"`, not
> `action == "opened"`.

## Examples

```cel
// Match on the X-GitHub-Event header
metadata.headers["x-github-event"] == "push"

// Same, via the resolved event type (requires event_type_selector:
// X-GitHub-Event on the webhook)
type == "push"

// Match on a body field
payload.action == "opened"

// Combine
type == "deployment_status" && payload.deployment_status.state == "success"
```

Use `github_signature_verified` in each rule that starts agent work or a
workflow, so that an unsigned delivery cannot start it:

```cel
github_signature_verified && type == "issues" && payload.action == "opened"
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

## Rule ordering

Matching rules run in ascending `ordinal` order, and for the release actions
that order is load-bearing rather than cosmetic:

1. `create_release` — creates the Imbi `Release` the rest key off.
2. `add_deployment_event` — looks the release up. When it is missing, the
   action records the deployment without a release, and the
   `deployment-sweep` maintenance operation attaches the release later. Put
   it after `create_release` so that the event attaches at once.
3. `publish_release` / `block_release` — ratify or block that release once the
   deployment reports its outcome.

Rules that key off a deployment state should enumerate the states they act on
rather than negating one. `state != "success"` sweeps in `inactive`, which
means the deployment was superseded by a newer one — the normal end of every
deployment's life, not a failure. The `publish_release` and `block_release`
actions enforce this themselves (they fire only on states mapping to `success`
and `failed` respectively), so a filter can be as broad as
`type == "deployment_status"`.

### Deployment states

The actions `add_deployment_event`, `publish_release`, and `block_release`
read the raw state with `status_selector` and map it to an Imbi deployment
status:

| Raw state | Imbi status |
|---|---|
| `queued` | `pending` |
| `pending` | `pending` |
| `in_progress` | `in_progress` |
| `success` | `success` |
| `failure` | `failed` |
| `error` | `failed` |
| `inactive` | `rolled_back` |

The actions skip any other state and log a warning. `publish_release` runs
only for `success`. `block_release` runs only for `failed`.

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
A failed evaluation logs a warning and is treated as non-matching for that
rule (it never raises into the request). Any other result is converted to a
boolean.

`substring(string, start[, end])` returns the characters from `start` up to,
but not including, `end`. Without `end`, it returns the rest of the string.
For example, `substring(payload.deployment.sha, 0, 7)` returns the short
commit SHA.

`substring()` works only in the CEL fields of a `handler_config`
(`committish_expression`, `version_expression`, `title_expression`,
`description_expression`). It does not work in a `filter_expression`: a
filter that calls it fails, and the rule does not match.

For the actions and their `handler_config` fields, see
[Gateway](index.md#built-in-actions).
