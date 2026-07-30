# 2. No encrypted credential store in v1

Date: 2026-07-28

## Status

Accepted

## Context

The scheduler design carries a `Credential` model — write-only, encrypted with
`IMBI_CONFIG_ENCRYPTION_KEY` via `encrypt_config_value`, with kinds `bearer`,
`basic`, `header`, `query_param`, and `hmac` — together with an `HttpTarget` for
arbitrary external URLs, an `identity.kind='credential'`, and optional HMAC
signing of `imbi-gateway` deliveries.

Three consumers were imagined for it:

1. **External `http` targets** — poking a foreign system that accepts a static
   key.
2. **Foreign service accounts** — running a task as some *other* Imbi service
   account, since no SA-to-SA exchange grant exists.
3. **HMAC signing** of scheduled gateway deliveries, where the target webhook's
   integration edge carries a signing secret.

Since then, agentic execution moved out of scope: the scheduler triggers
whichever service owns that work rather than running it. That removed the
largest prospective consumer of stored credentials. Of the three that remain,
(3) is explicitly discouraged in the design itself — it would duplicate a secret
the graph already holds, and the guidance is to schedule against unsigned
webhooks instead — and (1) and (2) are speculative: no concrete task needing
either has been named.

Meanwhile the subsystem is not free. It requires an encrypted-secret repository
layer, write-only API semantics with `has_secret` read models, per-kind
injection in the executor, scrubbing guarantees across logs and run rows, a
referenced-by check on delete, and a Helm change — `helm/imbi/templates/deployment.yaml`
does not currently wire `IMBI_CONFIG_ENCRYPTION_KEY` at all. Every one of those
is surface area holding secrets at rest for a consumer that may never arrive.

The design flags this as a question to settle *before* phase 1 fixes the data
model, because the `credentials` table and the `Credential` reference on targets
are schema, not implementation.

## Decision

Cut the credential subsystem from v1 entirely.

Removed from the model and the schema:

- `Credential` and the `scheduler.credentials` table
- `HttpTarget`, so `Task.target` is `ApiTarget | GatewayTarget`
- `identity.kind='credential'`, so `Identity.kind` is
  `delegated_user | service_account`
- `GatewayTarget.signing_credential` and HMAC signing
- All four `scheduler_credential:*` permissions and every `/credentials`
  endpoint
- The `IMBI_CONFIG_ENCRYPTION_KEY` Helm wiring, which is now unnecessary

The scheduler therefore stores **no secrets of any kind**. Its own service
account client credential arrives by environment variable, and the token it
buys with it is held in memory only. Delegated tokens are not obtained at all
in phase 1 — see [ADR 0003](0003-no-local-token-minting-bridge.md) — and when
the exchange grant lands they will be held in memory only, on the same terms.

A validation rule already planned for a different reason now covers the gap
cleanly: a target that resolves to an `imbi-*` service must be an `api` or
`gateway` target so that identity and disposition handling apply. With
`HttpTarget` gone, that rule is total — there is no way to express an outbound
call the scheduler cannot attribute.

## Consequences

### Positive

- **Zero secrets at rest**, which is a stronger version of the goal the design
  stated as "no long-lived user secrets at rest for Imbi targets," and it is
  verifiable by schema review rather than by audit.
- No Helm change, no second Fernet key in the scheduler's configuration, and
  no scrubbing obligation for credential material in logs or `scheduler_runs`.
- Phase 4 collapses to the `imbi-ui` surface.
- The task model gets smaller in the place where a mistake is most expensive:
  two target kinds and two identity kinds, each with a single resolution path.

### Negative

- **An external `http` target cannot be scheduled.** If one is wanted later,
  the honest answer in the meantime is an `imbi-gateway` webhook rule or an
  `imbi-api` endpoint that owns the outbound call — which is where the
  credential for that system probably belongs anyway, next to the integration
  that already holds it.
- **A task cannot run as a service account other than the scheduler's own.**
  System tasks run as `imbi-scheduler`, whose role must hold the global
  permission each trigger endpoint requires. This was already the model for
  system jobs; the loss is only the ability to borrow a different SA's identity.
- **Scheduled deliveries to a signing webhook are not possible.** Consistent
  with the design's own recommendation to prefer unsigned webhooks, and the
  cost surfaces immediately as a `no_effect` run rather than silently.
- Re-adding this is additive — a table, a model, and an injection step — not a
  migration of existing rows, because nothing depends on its absence.

## Alternatives Considered

### Model it now, implement it in phase 4

Put `Credential` and `HttpTarget` in the phase 1 schema and leave the endpoints
for later. **Rejected:** it commits the schema and the target union to a shape
chosen for a hypothetical consumer, and an unimplemented `kind='credential'` in
a validated enum is a trap — it either 422s (in which case it is documentation
pretending to be code) or it half-works.

### Keep `HttpTarget` without credentials

Allow unauthenticated external calls. **Rejected:** an outbound HTTP primitive
with a templated URL and body, callable on a schedule by anyone holding
`scheduled_task:create`, is a request-forgery surface with no compensating use
case yet.
