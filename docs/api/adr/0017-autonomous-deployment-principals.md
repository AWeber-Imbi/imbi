# ADR 0017: Autonomous Deployment Principals

Date: 2026-09-02

## Status

Accepted

The full design lives in the dev-environment repository's
`docs/autonomous-deployment-principals-functional-spec.md`. This ADR records
the `imbi-api`-side authorization decision: how a principal with no acting
user reaches a GitHub-backed deployment capability, and what bounds it.

Related: [ADR 0016](0016-delegated-execution-for-scheduled-jobs.md). That ADR
frames the general problem of work performed without an interactive human;
this is the *service-account* half. The delegated run-as-user half
(RFC 8693 token exchange, `scheduler:impersonate`) remains unimplemented and
is unchanged by this decision.

## Context

A service account presenting a client-credentials or SA API-key token could
not call any GitHub-backed deployment endpoint. The motivating consumer is a
daemon that rolls back misbehaving deployments and promotes well-behaved ones:
no human in the loop, therefore no browser, no OAuth consent, and no
`IdentityConnection`.

Four facts made this structural rather than a data gap:

1. **The identity challenge is aimed at a browser.** `attach_identity` stamps
   `actor_user_id = auth.user.id if auth.user else None`; `hydrate_identity`
   raises `IdentityRequiredError` when that is falsy, which becomes `401` plus
   `WWW-Authenticate: Imbi-Identity`. The sole purpose of that response is to
   make the UI render a Connect button.

2. **A service account cannot acquire the thing it is being asked for.**
   `IdentityConnection` is keyed `{integration_id, user_id}` and is only ever
   written by the interactive OAuth flow under `/me/identities/*`.

3. **The demand is an accident of unification.** With no explicit
   `identity_integration_id` on the capability binding,
   `effective_identity_integration_id` defaults to the serving Integration
   whenever that Integration also provides `identity`. The unified GHEC
   Integration provides both `identity` and `deployment`, so it became its own
   identity source. A deployment-only Integration would skip hydration
   entirely.

4. **The plugin layer was already capable.** `resolve_bearer` prefers a
   threaded-in `access_token` and otherwise mints an installation token from
   `app_id` + `private_key`. Every deployment call funnels through it.

The concern that prompted the work was the GHEC App's broad repository
permissions. Investigation found the Imbi-side control weaker than the
GitHub-side one:

- `project:deployment:write` is a single flat permission covering
  draft-notes, trigger, promote, cut, publish, and block/unblock.
- `require_permission` is global, with no project or organization scoping.
- Service accounts cannot use resource-level `CAN_ACCESS` ACLs — the fallback
  is `auth.user`-only.
- The deployment router is mounted with no `dependencies=` guard, and
  `_project_in_org` was called by only two endpoints. The `org_slug` path
  segment was decorative.
- `can_deploy` / `can_promote` are properties of the `Environment`, global to
  all callers. Nothing could express "this daemon may promote to staging but
  not production."

So a service account holding `project:deployment:write` reached every project
in every organization, and every environment, before any of this work.

## Decision

### The fallback is keyed on the principal, not the call site

`_resolve_and_context` previously chose between identity credentials and
service credentials on a per-caller `best_effort_identity` flag, which
correlated with "no acting user" only by coincidence. It now falls back
whenever `auth.user is None`, and `_has_service_credentials` accepts App
credentials on the same condition. `best_effort_identity` remains for callers
that want the fallback *with* a user present, and is now a superset of the
userless branch rather than a substitute for it.

### Three independent axes bound an authenticated userless principal

None subsumes another, and all are additive to the capability's own
permission:

1. **`integration:act-as-service`** — a new cross-cutting permission
   ("Use an Integration's own credential instead of the principal's
   identity"). A service account needs `project:deployment:write` *and* this,
   so an autonomous principal is a deliberate second grant rather than a side
   effect of a permission many service accounts already hold. Granted to no
   non-admin default role, mirroring `scheduler:impersonate`. The permission
   names the *act*, not the target, so `configuration`, `logs`, `lifecycle`,
   and `analysis` can adopt the same fallback unchanged.

2. **Organization membership** — enforced in `_resolve_and_context`, so every
   deployment endpoint inherits it. Service accounts already carry
   `MEMBER_OF` edges. This converts "any project in any organization" into
   "projects in organizations this service account was deliberately added
   to," and is the single highest-value control here.

3. **`Environment.allow_autonomous`** — default **false**, enforced alongside
   `can_deploy` / `can_promote`. `Environment` is the right home: it already
   carries deploy/promote authority in exactly this shape and inherits the
   existing admin UI and Cypher. Default-false means shipping this grants
   nothing until an operator opts an environment in. Encoding environment
   tiers into permission names would explode the permission set; a
   per-service-account environment allowlist would invent a new binding and a
   new UI for it.

Human callers are unaffected on all three. Their path, `CAN_ACCESS` ACLs
included, is unchanged.

### Imbi's own workers are exempt, via an explicit marker

`AuthContext.internal` is set only by `imbi.api.auth.principals.system_auth`,
which mints the synthetic principals the resync sweep, backfill, and promote
watcher act under. Those hold no granted permissions and no `MEMBER_OF`
edges, so checking either would deny work an operator authorized when they
configured the sweep. The field defaults to `False`, so every real
authentication path leaves it so.

The discriminator is an explicit field rather than the `best_effort_identity`
call-site flag or membership in `PROCESS_PRINCIPALS`. `best_effort_identity`
is set by some genuinely external callers — the gateway's service account
reaches `publish_release` with it — and `PROCESS_PRINCIPALS` means "hide this
name from activity feeds," which is not the same question.

### An autonomous principal cannot acknowledge a CI failure

`acknowledge_ci_failure` documents its meaning as "an operator who has seen
the failure and decided to ship anyway." A daemon setting it asserts
something nobody did, so it is refused with `403` — whether CI is red or
green, because the claim is false either way. This costs little: only
`'fail'` gates at all, so a rollback to a genuinely good ref is unaffected.
The only case denied is a daemon shipping a commit whose CI is failing, which
is precisely where a human belongs.

If real rollbacks turn out to be blocked, the escape hatch is a separate
`project:deployment:override-ci` permission — added on evidence, not in
anticipation.

### Installation tokens are minted for the operation, not the App

`_mint` posted to `/app/installations/{id}/access_tokens` with no body, so
every minted token carried the installation's full permission set. Each
deployment operation now declares the GitHub App permissions it needs and the
token is minted with exactly that set. The requested scope is part of the
token cache key — a correctness requirement, not an optimization: a
`contents: read` token served to a `contents: write` caller would fail at
GitHub at the worst possible moment. This bounds the pre-existing headless
sync paths at the same time.

### Failures are terminal `403`s with a discriminated `detail.error`

Following the existing `identity_required` shape:

| Condition | Status | `detail.error` |
|---|---|---|
| Userless principal lacks `integration:act-as-service` | 403 | `service_credential_forbidden` |
| App not installed on the repo | 403 | `app_not_installed` |
| Environment not autonomous-enabled | 403 | `environment_not_autonomous` |
| Principal not a member of the organization | 403 | `organization_forbidden` |
| Userless principal set `acknowledge_ci_failure` | 403 | `ci_override_forbidden` |
| No usable credential on the Integration | 503 | `no_service_credential` |

`403` rather than `424`/`503` for the terminal states because consuming
clients retry `5xx` on the assumption that it is transient, and none of these
will change on retry. Semantic precision loses to correct retry behavior; the
discriminator recovers the diagnostic information. `503` is retained for the
last row alone: a missing credential is one operator action away from being
fixed.

`app_not_installed` is raised by the plugin as
`PluginInstallationMissing` — a shared error type, so the host maps it
without importing a plugin — and is handled at the app level.

### Audit records the credential as well as the principal

`auth.principal_name` already attributes the action to the service account.
What was missing is what authority carried it out. Both the `Deployment` node
and the `operations_log` row now record e.g.
`github-app installation 12345678`. ADR 0016 established
`"{user} on behalf of {actor}"` for delegation; this is the mirror image.

It goes in the audit description blob and a dedicated node property rather
than into `recorded_by` / `performed_by`: those stay bare identifiers,
because the activity feed and `lookup_ops_log_performed_by` match on them.

The daemon's slug is deliberately **not** added to `PROCESS_PRINCIPALS`. That
set hides names from activity feeds as mere provenance; an autonomous
rollback is exactly the kind of event that should surface as an actor.

## Consequences

- A service account with `project:deployment:write`,
  `integration:act-as-service`, membership in the owning organization, and an
  opted-in target environment can drive the deployment capability with the
  Integration's GitHub App installation token and no `IdentityConnection`.

- **Existing external userless callers need the new grant.** The gateway's
  service account reaches `publish_release` today and will be refused with
  `service_credential_forbidden` until `integration:act-as-service` is granted
  to its role. This is an upgrade step, not a regression to work around — the
  point of the permission is that acting with an Integration's credential is
  an explicit decision.

- Installation tokens are cached per requested scope, so a process that both
  reads and writes holds more than one token per installation. That is the
  intended trade: an extra mint per distinct scope per hour, against every
  token in flight carrying the App's full grant.

- `effective_identity_integration_id` keeps defaulting to self. With the
  userless fallback in place the default is harmless for machine principals,
  and changing it would alter behavior for *human* callers: a user with a
  working GHEC connection would silently stop using their own token and start
  acting as the App, losing per-user attribution on GitHub.

- Credentials stay on the `Integration` and are selected by `?source=`. A
  service-account-scoped credential store would be a fourth secret location
  needing its own encryption, rotation, and audit surface, for no gain.

- Installation tokens stay in an in-process cache rather than Valkey. They are
  bearer secrets; moving them to a shared cache to save one mint per replica
  per hour is a poor trade. Process-wide sharing across principals is correct
  — the token belongs to the App installation, not to a principal, and the
  authorization decision already happened upstream.

- Organization scoping is enforced for userless principals only. That the
  deployment router enforces no organization membership for *anyone* is a
  pre-existing gap worth its own assessment.

- `project:deployment:write` remains coarse. Splitting it into per-action
  permissions would let a rollback daemon hold rollback authority without
  promote authority; the axes above bound the blast radius adequately without
  it, but the coarseness is real.
