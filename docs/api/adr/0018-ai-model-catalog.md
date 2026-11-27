# ADR 0018: AI Model Catalog

Date: 2026-09-04

## Status

Accepted. Amended on 2026-11-27: model resolution and default models (see
[Amendment: model resolution](#amendment-model-resolution)).

This ADR records how Imbi stores the LLM providers and models an organization
may call, and how it protects the credentials those providers need.

## Context

Before this change, Imbi read its LLM configuration from the environment only.
`IMBI_ANTHROPIC_*` and `ANTHROPIC_API_KEY` supplied one credential for the
whole deployment. Each of `imbi.common`, the assistant, and the Slack bot
carried its own hard-coded default model. Nothing in the graph knew that a
provider or a model existed.

An agentic-harness feature needs more than that. Four requirements drove the
design:

1. **The catalog is per organization.** Two organizations in one Imbi
   deployment must be able to call different providers, with different
   credentials, and different models.
2. **Credentials must be manageable at runtime.** An operator must be able to
   rotate a key without a redeploy, and must be able to tell two keys apart
   after they are stored.
3. **Access must be narrower than the organization.** Some models are
   expensive, or are restricted by contract. An admin must be able to limit a
   model to named teams.
4. **Typing vendor model ids by hand does not scale.** Providers publish their
   own model lists. Imbi must be able to read them.

## Decision

### Drivers are static code, providers are graph nodes

A *driver* is the request shape Imbi uses to talk to a vendor. The five
drivers are `anthropic`, `openai`, `openai_compatible`, `bedrock`, and
`vertex`. They live in `imbi.common.llm.drivers` as a static tuple of
`DriverInfo` records, and `GET /ai-provider-drivers` serves them.

An `AIProvider` node exists only after an admin configures one. Creating an
organization therefore implies no AI configuration, and adding a driver is a
release rather than a data backfill.

The catalog carries what the admin UI needs to render a driver it has no node
for: display name, description, default base URL, `supports_iam`,
`requires_base_url`, `supports_discovery`, and an icon name. The UI shows an
unconfigured driver as a ghost row with a **Set up** action.

### `AIModel` carries an explicit access scope

`AIModel` is a node with a `SERVED_BY` edge to its provider, a `BELONGS_TO`
edge to the organization, and zero or more `ALLOWED_FOR` edges to teams.

`access_scope` is stored, not inferred. It is `organization` or `restricted`.
A `restricted` model must name at least one team, and the endpoint rejects an
empty team list with `422`. Inferring "every team" from zero edges would make
"available to everyone" and "nobody has picked teams yet" the same state.

The organization edge is denormalized onto the model as well as onto the
provider. Every scoping query then needs one hop instead of two.

### Credentials are encrypted, and the response carries a hint

A provider's API key is accepted as plaintext, encrypted immediately with
`imbi.common.auth.encryption.encrypt_config_value`, and stored only as
`credentials_encrypted`. The key is never returned, echoed, or logged.

Responses carry three fields instead: `has_credentials`, `credential_hint`,
and `credential_updated_at`. The hint is the last four characters of the key,
stored in the clear at write time, and is omitted for keys shorter than eight
characters so a short secret is never exposed whole. This goes one step past the boolean-only
masking the MCP server endpoints use. The step is deliberate. An operator who
holds two keys for one vendor cannot otherwise tell which key is installed.

`auth_kind` is derived, never stored. A stored key reports `api_key`. A driver
that authenticates from ambient cloud credentials reports `iam`. Everything
else reports `none`.

### Credentials have their own permission

Five permissions guard the catalog: `ai_model:create`, `ai_model:read`,
`ai_model:update`, `ai_model:delete`, and `ai_model:credentials`.

`ai_model:credentials` is separate from `ai_model:update` on purpose. Changing
a model's default temperature must not imply the right to replace the
organization's production API key. Only `PUT` and `DELETE` on
`/ai-providers/{id}/credentials` require it.

`ai_model:read` is granted to the same default roles that hold
`environment:read`. The other four are admin-only.

### URLs address nodes by id, and every query re-checks the organization

Every route is mounted under `/organizations/{org_slug}`, and every Cypher
query matches both the node id and the `BELONGS_TO` edge to that organization.
A valid id under the wrong organization returns `404`, which is
indistinguishable from a missing node. Cross-organization probing is therefore
not possible through these routes.

`slug` remains a stable org-scoped alias. Agent configuration can name
`default-chat` instead of a vendor model id. Both uniqueness rules are scoped.
Model `slug` is unique per organization; the `(org_id, slug)` unique index
enforces it (see the amendment below). `model_id` is unique per provider; the
endpoint enforces it, because no graph index covers it.

### Deleting a provider does not cascade

`DELETE /ai-providers/{id}` returns `409` while the provider still serves
models. Delete or move the models first.

A cascade would silently remove catalog entries that agent configuration
refers to by slug. The meaningful distinction is not built-in against custom.
It is referenced against unreferenced.

### `monthly_spend_cap` is advisory

The field is stored and shown, and nothing enforces it. Imbi has no spend
tracking yet. The field help text in the model dialog says so directly. The
alternative was to omit the field until enforcement ships, which would lose
the number an admin already knows.

Costs are stored as `Decimal | None` in USD per one million tokens. `None`
means unknown or contract pricing. `0` means self-hosted.

### Discovery reads the provider's own model list

`POST /ai-providers/{id}/discover` calls the provider with its stored
credential and returns the models it reports. It writes nothing.
`POST /ai-providers/{id}/import-models` then creates nodes from the selection.

`anthropic` uses the `anthropic` SDK, which is already a dependency, and maps
`max_input_tokens` and `max_tokens` into `context_window` and
`max_output_tokens` when the provider supplies them. `openai` and
`openai_compatible` call `GET {base_url}/models` over httpx. `bedrock` calls
`ListFoundationModels` on `bedrock.{region}.amazonaws.com` over httpx, with
the stored key as a bearer token or SigV4 from the runtime IAM role, and keeps
active text models with on-demand inference. It also calls
`ListInferenceProfiles` for system-defined profiles and keeps the active
profiles of text models by profile ID, because current Claude models are
available only through a profile. `vertex` calls the
`v1beta1` `publishers/google/models` list with the express key and keeps the
Gemini models. The express mode API reference does not include that method,
so a 401 or 403 for `vertex` is a 422 that tells the admin to add models by
ID. `supports_discovery` on the driver lets the UI hide the action.

Discovery doubles as the connection test for a stored key. Every failure is
normalized to a message that names the driver and the transport error or HTTP
status. Provider response bodies never reach the caller, because a provider
can echo the key back in an error body.

`base_url` is validated at write time. The scheme must be `http` or `https`,
a host is required, and embedded userinfo is rejected. Outbound calls carry a
ten-second timeout, and auto-pagination stops at 1000 models.

## Alternatives Considered

**Seed built-in providers as nodes for every organization.** Rejected. It
couples organization creation to AI configuration, and it needs a backfill
every time a driver is added. It also gives an organization rows it never
asked for.

**Merge a static catalog into the read path instead of storing providers.**
Rejected. Credentials, base URLs, regions, and enable state are per
organization and must be written somewhere. A hybrid read path hides that
half the row is stored and half is code.

**Allow a per-model API key override.** Rejected. It complicates rotation,
masking, auditing, and resolution, and it makes "which key did this call use"
a per-model question. Two credential sets means two provider instances, such
as "OpenAI Production" and "OpenAI Research". The design mockup gated this
field behind a flag already.

**Move identity and uniqueness into relational tables.** Rejected. Every other
Imbi entity is a graph node, and both uniqueness rules here are scoped rather
than global. Consistency with the rest of the model wins, and scoped
uniqueness is enforced in the endpoint elsewhere in Imbi too.

**Return only a boolean for credential state.** Rejected. It is the safer
default, and it fails the operator who must confirm which of two keys is
installed. Four characters of a key are not enough to use it.

## Consequences

- An organization can hold several providers for one vendor, each with its own
  key. Attribution and rotation stay per provider.
- The catalog is inert until something consumes it. The assistant, the Slack
  bot, and the harness still read their model from the environment. A resolver
  is the next piece of work.
- `IMBI_CONFIG_ENCRYPTION_KEY` becomes a hard prerequisite for storing a
  provider credential. Writing a key without it raises at runtime, and
  changing it makes every stored credential unreadable.
- The last four characters of every provider key are stored in the clear. This
  is an accepted disclosure. A four-character suffix is not a usable secret.
- Discovery performs an outbound HTTP call to an address an admin supplied for
  `openai_compatible` providers. Scheme and host validation bound the obvious
  cases. Runtime SSRF controls are not in place.
- Deleting a team leaves its `ALLOWED_FOR` edges behind. A restricted model can
  therefore end up pointing at a team that no longer exists.
- Providers can be edited and deleted through the API only. The admin UI
  creates providers, manages their credentials, and manages their models.

## Amendment: the catalog becomes per organization (2026-11-27)

The first implementation did not follow this ADR. `AIProvider` and `AIModel`
were global, with no `BELONGS_TO` edge, slugs unique across the installation,
and routes at `/ai-providers` and `/ai-models`. The code now follows the
decision above:

- Each `AIProvider` and `AIModel` has a `BELONGS_TO` edge to one organization
  and an `org_id` property. The `(org_id, slug)` unique index makes the slug
  unique in the organization. The global slug indexes are dropped.
- The routes are under `/organizations/{org_slug}/ai-providers` and
  `/organizations/{org_slug}/ai-models`. The caller must be a member, and the
  `ai_model:*` permissions of the caller's role in that organization apply.
- Every consumer reads only the catalog of its organization: prompt runs,
  workflow steps, agent saves, task claims, and usage prices. A global prompt
  names a model by slug, and a run uses the model with that slug in the
  organization of the run.
- The assistant and the Slack bot still take their model from the
  environment (`IMBI_ASSISTANT_MODEL`, `IMBI_SLACKBOT_MODEL`). Only the model
  of their CMS system prompt comes from a catalog: the catalog of the
  organization of the conversation for the assistant, and the catalogs of
  the organizations of the user for the Slack bot. Model selection through
  an organization catalog is a follow-up (the resolver below).
- `IMBI_AI_PROVIDER_<SERVICE>` names a provider as
  `<org-slug>/<provider-slug>`, not by id.

Migration: the `ai-catalog-org-copy` maintenance operation copies each
global provider (with its encrypted
key, hint, workload identity, and timestamps) and each global model to every
organization, as new nodes with new ids. A copy of a model keeps the
`ALLOWED_FOR` edges only to the teams of its organization. Only the copy in
the organization of a workload identity keeps it; each other organization
sets up its own: the API sets the identity of the organization of the
provider. Then it
deletes the global nodes. Slugs do not change. The copy runs in one
transaction under an advisory lock, and does nothing when no global node is
left. With no organization, the global nodes stay.

The spend cap is per organization per model, because each organization has
its own copy of a model.

## Follow-ups

- The harness, the assistant, and the Slack bot on the resolver (see the
  amendment).
- Vertex discovery with service account credentials. They need
  `google-auth`, which is not a dependency. Bedrock application inference
  profiles are not listed.
- Spend tracking against `monthly_spend_cap`, and pricing history.
- A capability set on models, such as `tool_use`, `vision`, and
  `structured_output`, replacing the coarse `kind` field.
- Runtime SSRF controls on outbound calls to custom base URLs.
- Team deletion must remove or block on `ALLOWED_FOR` edges.

## Amendment: model resolution

Date: 2026-11-27

### Default model edges

`Organization -[:USES_DEFAULT_MODEL]-> AIModel` and
`Team -[:USES_DEFAULT_MODEL]-> AIModel` name the default model of an
organization and of a team. Each source node has at most one edge. The
endpoint replaces the edge in one transaction under an advisory lock on the
source node.

- A default model must be a generative model of the organization.
- A team default must be a model that the team may use: an `organization`
  scope model, or a `restricted` model with an `ALLOWED_FOR` edge to the team.
- `DELETE /organizations/{org_slug}/ai-models/{id}` returns `409` while the
  model is a default.
- `GET`/`PUT /organizations/{org_slug}/default-ai-model` needs
  `ai_model:read`/`ai_model:update`. `GET`/`PUT
  /organizations/{org_slug}/teams/{slug}/default-ai-model` needs
  `team:read`/`team:update`. No new permission is added.

### Resolution order

`imbi.common.llm.resolve.resolve_model` finds the model of a call:

1. The explicit model (the prompt version, the prompt run, or the workflow
   step), by id or slug, in the catalog of the organization of the call.
2. The default of the team of the call. The team must belong to the
   organization of the call.
3. The default of the organization.
4. The environment model of the service.

The first level that names a model wins. When that model is missing, is
disabled, has a disabled provider, or does not allow the caller, the resolver
raises `ModelUnusable` with the reason `not_found`, `disabled`,
`provider_disabled`, or `not_allowed`. It does not try the next level. This
replaces the soft fallback to the environment model in
`imbi.common.prompts.system`. The environment model applies only when no
level names a model.

A `restricted` model must allow the user of the call (through a team), the
team of the call, or both when both are known. With neither, the model is
refused. An admin can use every model.

The consumers today:

- A prompt run: `403` (`model_not_allowed`) or `422`, as before. A
  generative run uses the team and organization defaults; the team is the
  owner team of the workflow for a workflow step prompt.
- A workflow Model decision step: the step fails with `model_unavailable`.
  The model must allow the owner team of the workflow.
- The system prompts of the assistant, the Slack bot, and the API helpers
  (ticket subject, descriptions): a version model that cannot be used, or one
  that a driver other than `anthropic` serves (`unsupported_driver`), is an
  error. The assistant returns `403` or `422`, the Slack bot replies with an
  error, and an API helper returns its fallback marked `degraded`. These
  consumers do not read the defaults yet. Their prompts are global, so the
  model comes from the catalogs of the organizations of the user. Without a
  user, there is no catalog model and the configured model is used.

## References

- [Administration: AI Models](../../admin/ai-models.md)
- [ADR 0002: Authentication and Authorization](0002-authentication-and-authorization-architecture.md)
- `apps/api/src/imbi/api/endpoints/ai_providers.py`
- `apps/api/src/imbi/api/endpoints/ai_models.py`
- `libraries/common/src/imbi/common/llm/drivers.py`
- `libraries/common/src/imbi/common/llm/discovery.py`
