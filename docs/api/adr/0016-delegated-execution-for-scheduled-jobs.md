# ADR 0016: Delegated Execution for Scheduled Jobs

Date: 2026-06-29

## Status

Accepted

Implementation is phased; the full design lives in
[`imbi/docs/imbi-scheduler-functional-spec.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/imbi-scheduler-functional-spec.md).
This ADR records the `imbi-api`-side decision only — the new delegation
primitive and the migration of the in-process scheduled loops off the API
process. The standalone `imbi-scheduler` service itself is a separate repo and
not in scope for this ADR log.

## Context

Imbi has grown to need general-purpose scheduled execution, and the platform
has accumulated scheduling-like behavior in an ad-hoc way:

1. **No general scheduler exists.** There is no APScheduler, cron daemon, job
   registry, or recurring-job domain model anywhere in the stack. The graph
   vlabel set (`imbi.common/graph/schemata.toml`) has no `Schedule`/`Job`/
   `Task`/`Trigger` label. `pg_cron` is preloaded and `CREATE EXTENSION`'d but
   unused.

2. **The only existing "scheduled" job is hand-rolled.** `imbi.api/scoring/
   queue.py:451-510` (`run_daily_tick`) is a polling loop on `asyncio.sleep`
   that fires once per UTC day at `DAILY_TICK_HOUR_UTC=6`, using a Valkey
   `SETNX` 25h-TTL lock keyed `imbi:score-recompute:daily:<date>` for
   cross-worker single-firing, then enqueues every project for
   `scheduled_recompute`. It is hardcoded to one task and not generalizable.
   Three more in-process consumer loops (commit-sync, PR-sync,
   identity-sweeper) are wired through `lifespans.py` and run inside the API
   process.

3. **`imbi-automations` is a one-shot CLI, not a scheduler.** It runs workflow
   TOMLs across projects when invoked manually (`just run <workflow>`); it has
   no recurring-execution capability. The missing piece is a trigger layer.

4. **Planned features need scheduling.** Dynamic blueprint-field
   recalculation (e.g. `min(date) where foo = bar` over an applied blueprint
   field) requires periodic re-evaluation. There is no mechanism to schedule
   that today.

The platform has decided to introduce a **standalone `imbi-scheduler` service**
(APScheduler 4.x, owning its own job store and run history) that triggers
`imbi-api` REST calls on schedules. See the functional spec for that service's
design; this ADR covers what `imbi-api` must provide for it to work.

The hard requirement that drives this ADR: scheduled jobs must be able to
**execute as the scheduling user** — i.e. with that user's identity and
permissions, including resource-level `CAN_ACCESS` ACLs — and also as the
scheduler's own service account for system jobs.

The blocker: **`imbi-api` has no impersonation or delegation primitive.**
`AuthContext` (`auth/permissions.py:43-86`) is always the principal that
presented the token. Service accounts cannot use resource-level ACLs
(`permissions.py:907-913` — the `CAN_ACCESS` fallback is `auth.user`-only),
and admin bypass is `User`-only (`permissions.py:745`). There is no "act on
behalf of" path, no `act`/`azp` claim, and no consent model. So "run as a user"
cannot be satisfied by any existing mechanism.

## Decision

Add a **delegated-execution primitive** to `imbi-api` based on OAuth2 token
exchange (RFC 8693), plus a **consent model**, so the scheduler can obtain
short-lived JWTs scoped to a target user. The scheduler holds no user
secrets.

### 1. Token-exchange grant

Add a branch to `POST /auth/token` (`endpoints/auth.py:325-499`) for:

```
grant_type        = urn:ietf:params:oauth:grant-type:token-exchange
subject_token     = <scheduler SA client-credential JWT>   (or client_id+secret)
requested_subject = <target user email>
scope             = <scope covered by a Consent>
```

`imbi-api` validates that (a) the scheduler SA is authenticated and holds the
new `auth:delegate` permission, (b) a non-expired, non-revoked `Consent`
exists for `(user, 'imbi-scheduler', scope ⊇ requested)`, and (c) the target
user is active. It then mints a short-lived access JWT via
`imbi.common.auth.core.create_access_token` carrying:

```
sub          = <target user email>
auth_method  = 'token_exchange'
act          = { client_id: <scheduler SA> }   # RFC 8693 `act` claim
azp          = <scheduler SA slug>
scope        = <granted scope>
jti          = new; TokenMetadata node ISSUED_TO the user, linked to the SA
```

### 2. Consent model

Add a **`Consent`** graph node recording that a user authorized the scheduler
to act on their behalf for a scope. `Consent` is recorded under the **user's
own** authenticated session (the scheduler passes the user's JWT through when
creating a schedule), so `imbi-api` attributes consent to the real user — the
scheduler never records consent on a user's behalf:

```
Consent:
  user_email, actor_sa ('imbi-scheduler'), scope,
  created_at, expires_at?, revoked_at?
```

Endpoints: `POST /consents` (records under caller identity), `GET /consents`,
`DELETE /consents/{id}` (revoke). v1 uses one broad scope (`imbi-api:*`) per
user; finer per-resource-type scopes are a deferred refinement.

### 3. `AuthContext.actor`

`AuthContext` gains an `actor: ServiceAccount | None` field populated when
`auth_method == 'token_exchange'`. Permission resolution uses the **user's**
permissions (including `CAN_ACCESS` resource ACLs — the whole point of
delegation). `principal_name` remains the user; a new `actor_name` property
returns the scheduler SA. Audit/`requested_by`-style attribution records
`"{user} on behalf of {actor}"`. The `act`/`azp` claim is verified on every
request, not only at exchange.

### 4. New permission & service account

Seed a new `auth:delegate` permission. Provision an `imbi-scheduler` service
account (`POST /service-accounts`) with a client credential
(`POST /service-accounts/{slug}/client-credentials`) whose role grants
`auth:delegate` plus the global permissions each system job needs (resource
ACLs are user-only, so system jobs require global perms — document the set
per migrated task). System jobs authenticate directly with the SA's
client-credential JWT (refreshed proactively, the
`imbi-automations/clients/imbi.py:_AuthManager` pattern); user jobs exchange
for a delegated token at fire time.

### 5. Migrate the score-recompute daily tick

Externalize the trigger of `run_daily_tick` to the scheduler; **keep the
worker/queue logic in `imbi-api`** (the `imbi:score-recompute` Valkey-stream
consumer stays). Concretely: expose (or reuse) an HTTP trigger —
`POST /api/scoring/recompute-all` guarded by a new
`scoring:trigger-scheduled` (or `scoring:recompute`) permission — that
enqueues every project with reason `scheduled_recompute`. Remove
`run_daily_tick` and its task from `score_worker_hook`
(`lifespans.py:202-237`); keep `consume_recompute`. The scheduler seeds a
system schedule `0 6 * * *` → `POST /api/scoring/recompute-all`. The Valkey
per-date `SETNX` dedupe lock is no longer needed (APScheduler's shared data
store guarantees single firing across replicas); the existing per-project
debounce + idempotency in `enqueue_recompute` remains as a backstop.

The remaining in-process loops (identity-token sweeper, commit/PR-sync pause
sweeps) are assessed per-task as follow-ups; only score recompute is in the
first cut.

## Alternatives Considered

### A. Per-user API keys stored by the scheduler

Users mint `ik_…` API keys and register them with the scheduler, which stores
them encrypted and replays them at fire time. **Rejected:** the scheduler
becomes a custodian of long-lived user secrets; keys don't expire unless
rotated; revocation is manual and scattered; and it conflates "a credential
the user happened to create" with "an authorization to act." Token exchange
keeps secrets server-side and makes consent an explicit, revocable record.

### B. Run everything as a service account with `requested_by` attribution only

Every job runs as the scheduler SA; the originating user is recorded as
`requested_by`/`actor` for audit only, not as the security principal.
**Rejected for user jobs:** this does not satisfy "execute as them." The job
would run with the SA's global permissions and could not pass resource-level
`CAN_ACCESS` checks, so a user-scheduled job targeting a resource they can
access but the SA cannot would 403. This remains the model for **system**
jobs, where it is correct.

### C. `pg_cron` driving DB-side jobs

The Postgres image already loads `pg_cron`. **Rejected as the primary
engine:** it can only run SQL, not call arbitrary `imbi-api` endpoints or
speak the auth/delegation flow, and it couples scheduling to the database
process. It may still be useful for pure-SQL maintenance later, but it is not
the general scheduler. The standalone APScheduler service is the engine.

### D. Build the scheduler inside `imbi-api` (in-process)

Add APScheduler to `imbi-api` and run schedules as a lifespan loop, reusing
the existing auth context directly. **Rejected:** the platform has
explicitly chosen a standalone scheduler repo (separable deploy/scaling,
independent failure domain, and a clean home for run-history that does not
belong in the graph). The delegation primitive is precisely what lets a
separate service run as a user safely.

## Consequences

### Positive

- **True run-as-user.** Delegated JWTs run with the user's full permissions,
  including resource ACLs that service accounts cannot use — the capability
  that did not exist before.
- **No stored user secrets.** The scheduler stores a `consent_id`, not user
  tokens or passwords. The decisive security advantage over per-user keys.
- **Explicit, revocable authorization.** Consent is a first-class, auditable
  graph node; revoking a schedule or consent stops future exchanges.
- **Short-lived, revocable delegated tokens** with `jti`-tracked
  `TokenMetadata`, reusing the existing revocation machinery.
- **General scheduler replaces a hand-rolled loop.** The score daily tick
  becomes one cron entry; future scheduled work (dynamic field recalculation,
  `imbi-automations` triggers) has a home.
- **Attribution is honest.** `actor_name` + `principal_name` make "who caused
  this and on whose behalf" explicit in logs and audit.

### Negative

- **New grant type + `AuthContext.actor` + `Consent` model is real surface
  area** in `imbi-api`: auth is the most security-sensitive part of the
  system, and this touches `authenticate_jwt`, token issuance, and the
  permissions module. Requires thorough tests (consent required, scope
  checked, short-lived, revocable, `act`/`azp` verified on every request).
- **Two systems must agree on consent lifecycle.** The scheduler stores
  `consent_id`; `imbi-api` owns the `Consent` node. A revoked/consent or
  deleted schedule must suppress firings (the scheduler re-checks consent
  before each exchange and treats a failed exchange as a `skipped` run).
- **System jobs need global permissions.** Because resource ACLs are
  user-only, every system job's SA role must hold the global permission for
  the endpoint it calls. This widens the scheduler SA's blast radius; it is
  mitigated by scoping the role to exactly the trigger endpoints and by
  preferring delegated (user) jobs where the action is user-scoped.
- **Migration moves a working path.** The score daily tick works today; moving
  it introduces a transitional risk. Mitigated by keeping per-day idempotency
  so a double-fire is harmless even before APScheduler's single-firing
  guarantee applies.

### Risks Accepted

- **Broad v1 consent scope (`imbi-api:*`).** A consenting user authorizes the
  scheduler to call any `imbi-api` endpoint as them. Acceptable for an
  internal, admin-curated platform for v1; finer scopes are an explicit
  follow-up (functional spec §15).
- **Delegated token lifetime (5–15 min).** Chosen short; a job making many
  calls reuses the token until expiry then re-exchanges. Not a refresh-token
  family for v1.
- **Target-path allow-listing deferred.** v1 allows arbitrary `imbi-api`
  method+path as a job target. If abuse becomes a concern, restrict to an
  allow-list per scope (functional spec §12).

## References

- [`imbi/docs/imbi-scheduler-functional-spec.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/imbi-scheduler-functional-spec.md)
  — Full scheduler service design, data model, REST API, and phased plan.
- ADR 0002: Authentication and Authorization Architecture (the auth system
  this extends — JWTs, service accounts, API keys, permission model).
- [RFC 8693: OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693)
  — `act`/`azp` claims and the token-exchange grant type.
- `imbi.api/auth/permissions.py:43-86,306-417,907-913` — `AuthContext`,
  `authenticate_jwt`, and the user-only `CAN_ACCESS` fallback that motivates
  delegation.
- `imbi.api/scoring/queue.py:451-510` and `imbi.api/lifespans.py:202-237` —
  the `run_daily_tick` loop being externalized.
- `imbi-automations/src/imbi_automations/clients/imbi.py:87-180` — the
  `_AuthManager` reference pattern for SA client-credential refresh.
