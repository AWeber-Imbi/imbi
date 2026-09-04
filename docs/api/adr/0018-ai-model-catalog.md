# ADR 0018: AI Model Catalog

Date: 2026-09-04

## Status

Accepted

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
`default-chat` instead of a vendor model id. Both uniqueness rules are scoped,
so both are enforced in the endpoint rather than by a graph index: model
`slug` is unique per organization, and `model_id` is unique per provider.

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
`openai_compatible` call `GET {base_url}/models` over httpx. `bedrock` and
`vertex` are not supported, and `supports_discovery` on the driver lets the UI
hide the action.

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

## Follow-ups

- A resolver in `imbi.common.llm` that the harness, assistant, and Slack bot
  call. Resolution order is agent override, then team default, then
  organization default, then the environment fallback. A disabled provider or
  model is a hard configuration error.
- `Organization -[:USES_DEFAULT_MODEL]-> AIModel`, and the per-team equivalent.
- Discovery for `bedrock` and `vertex`. Both need client libraries that are
  not dependencies today.
- Spend tracking against `monthly_spend_cap`, and pricing history.
- A capability set on models, such as `tool_use`, `vision`, and
  `structured_output`, replacing the coarse `kind` field.
- Runtime SSRF controls on outbound calls to custom base URLs.
- Team deletion must remove or block on `ALLOWED_FOR` edges.

## References

- [Administration: AI Models](../../admin/ai-models.md)
- [ADR 0002: Authentication and Authorization](0002-authentication-and-authorization-architecture.md)
- `apps/api/src/imbi/api/endpoints/ai_providers.py`
- `apps/api/src/imbi/api/endpoints/ai_models.py`
- `libraries/common/src/imbi/common/llm/drivers.py`
- `libraries/common/src/imbi/common/llm/discovery.py`
