# 3. No local token-minting bridge

Date: 2026-07-28

## Status

Accepted

## Context

`imbi-api` has no delegation primitive yet: ADR 0016 is accepted and entirely
unimplemented, and `POST /auth/token` dispatches only `authorization_code`,
`refresh_token`, and `client_credentials`. So delegated (run-as-user) tasks
cannot work until the token-exchange grant ships.

There is, however, a shortcut. `imbi.common.auth.core.create_access_token`
accepts an email and returns a valid access token, and any service holding
`IMBI_AUTH_JWT_SECRET` can call it. `imbi.slackbot.identity.mint_token` does
exactly this today and injects the result as the bearer for every tool call. The
scheduler could do the same and deliver run-as-user before ADR 0016 lands.

The scheduler design accordingly specified a bridge: `IMBI_SCHEDULER_ALLOW_LOCAL_MINT`,
defaulting to false, refused outside development unless set explicitly, limited
to tasks whose subject equals their creator, never combined with
`scheduler:impersonate`, recording `identity_kind='minted'` on every run so the
audit gap is visible, and deleted rather than deprecated once the exchange grant
ships. Its own recommendation was to build phase 1 with service-account identity
only and skip minting; the flag existed to make the alternative explicit.

What changed is sequencing. Phase 2 — the `Consent` model, the token-exchange
grant, `AuthContext.actor` — is being built in the same worktree as phase 1
rather than deferred to unscheduled work. The bridge's entire justification was
the gap between the two phases, and that gap is now measured in days of the same
branch.

## Decision

Do not build the bridge. No `IMBI_SCHEDULER_ALLOW_LOCAL_MINT` setting, no
minting code path, no `identity_kind='minted'` value in the run model.

Phase 1 supports `identity.kind='service_account'` only. Creating a task with
`kind='delegated_user'` returns 422 with a pointer to the delegation work until
phase 2 lands, at which point it starts working through the exchange grant.

## Consequences

### Positive

- The audit gap this service could have introduced is never introduced. There
  is no window in which a `scheduler_runs` row says a user did something the
  user never consented to.
- Nothing to delete later, so no risk that the "temporary" path outlives its
  exit criteria — the common fate of flags like this one.
- One fewer setting, one fewer identity kind, one fewer branch in identity
  resolution, and one fewer value in the run-state vocabulary.

### Negative

- **Delegated tasks do not work until phase 2 lands.** Phase 1 delivers system
  tasks on the scheduler's service account, which is the correct model for the
  work being migrated first (the score-recompute daily tick is a system task).
  A user wanting a run-as-user task waits for phase 2 rather than getting a
  version whose attribution is a lie.
- If phase 2 were to slip badly, this decision would have to be revisited. That
  is a scheduling risk, not a design one, and reversing it is adding back a
  gated code path.

## Note on the wider hole

Removing the scheduler's minting path does not close the platform's. Any service
holding `IMBI_AUTH_JWT_SECRET` can still mint a token for any user with no
consent record, no `act` claim, no `jti` in `TokenMetadata`, and nothing in
audit distinguishing it from that user logging in — and `imbi-slackbot` ships
that today.

The case for token exchange is therefore **consent, attribution, and
revocation**, not capability; ADR 0016's claim that "run as a user cannot be
satisfied by any existing mechanism" is not accurate. Delegation only closes the
hole once local minting stops being supported. Retiring
`imbi.slackbot.identity.mint_token` in favor of the exchange grant is an
`imbi-api` and slackbot decision, out of scope here, and recorded so it is not
left implicit.
