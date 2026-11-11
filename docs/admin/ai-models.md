# AI Models

The **AI Models** section holds the catalog of AI models Imbi may call. The catalog has two levels. A **provider** is one
configured endpoint, with its own credential. A **model** is one model that
provider serves.

The catalog is global. Every organization in the deployment shares the same
providers, credentials, and models. Use [Team access](#team-access) to limit a
model to some teams.

Open the section at **Admin > Global Admin > AI Models**.

!!! note
    The assistant and the Slack bot use a catalog model when their prompt
    version names one that an Anthropic provider serves. See
    [Prompts](prompts.md#model-and-parameters).

## Drivers

A **driver** is the request shape Imbi uses to talk to a vendor. Drivers are
built in. You cannot add one from the UI.

| Driver | Base URL | Credentials | Discovery |
|---|---|---|---|
| Anthropic | Optional. Defaults to `https://api.anthropic.com` | API key | Yes |
| OpenAI | Optional. Defaults to `https://api.openai.com/v1` | API key | Yes |
| OpenAI-compatible | **Required** | API key | Yes |
| AWS Bedrock | Not used | API key, or the runtime IAM role | No |
| Google Vertex AI | Not used | API key, or the runtime IAM role | No |
| TypeSafe | Optional. Defaults to `https://api.typesafe.ai/v1` | API key | No |

Use **OpenAI-compatible** for any endpoint that implements the OpenAI
chat-completions API, such as vLLM, Ollama, or a gateway.

AWS Bedrock and Google Vertex AI can authenticate from the credentials of the
process Imbi runs as. A provider on either driver with no stored key reports
**IAM role**. Setting a key overrides the role for every model under that
provider.

TypeSafe serves **decision models**, such as Jev (`jev-latest`). A decision
model returns typed judgments and probabilities instead of text. TypeSafe has
no model-list endpoint, so add each model manually.

The section lists every driver. A driver with no provider configured appears
as a greyed row with a **Set up** action.

## Add a provider

1. Click **Add provider**, or click **Set up** on a driver row.
2. Select the driver. The description below the field explains what it calls.
3. Enter a name. The name identifies this provider in every model list.
4. Enter the base URL. Leave the prefilled default for Anthropic and OpenAI.
   OpenAI-compatible requires a URL.
5. Enter the region for AWS Bedrock, or the region and project ID for Google
   Vertex AI.
6. Paste an API key. This field is optional. You can set the key later.
7. Enter a description. This field is optional.
8. Click **Create provider**.

The base URL must use `http` or `https`, must include a host, and must not
embed a username or a password. Imbi rejects any other URL.

Configure one provider for each credential. To run two Anthropic keys, create
two Anthropic providers, such as "Anthropic Production" and "Anthropic
Research". A model cannot override its provider's key.

## Manage credentials

Click the key icon on a provider row to open the credentials dialog.

- **To set or replace a key**, paste the key and click **Save key**. A
  replacement takes effect on the next request from every model under the
  provider.
- **To remove a key**, click **Remove key**. Models under the provider can no
  longer be called, unless the driver falls back to an IAM role.

Imbi encrypts the key before it stores it. The key is never returned by the
API, shown in the UI, or written to a log.

The dialog and the provider row show three things instead of the key:

- Whether a key is set.
- The last four characters of the key, as `••••abcd`. Use this to tell two
  keys apart. Keys shorter than eight characters get no hint.
- When the key was last changed.

!!! warning
    Storing a credential requires `IMBI_CONFIG_ENCRYPTION_KEY`. Set it before
    you save a key. See
    [Config Encryption](../common/api/auth.md#config-encryption). If you
    change the key, every stored credential becomes unreadable and must be
    entered again.

Setting or removing a credential requires the `ai_model:credentials`
permission. Editing a model does not grant it.

## Use workload identity instead of a key

An Anthropic or OpenAI provider can get a short-lived token through
workload identity federation, so that Imbi stores no key. The provider must
use the default base URL and have no stored key. The dialog shows the
workload identity target only when the plugin of the vendor (`anthropic` or
`openai`) is installed and enabled. The
[Workload Identity Runbook](workload-identity.md) gives the vendor setup.

1. Select the organization whose identity source signs the tokens. The
   organization needs an identity source; see
   [Workload identity](secrets.md#workload-identity).
2. Click the key icon on the provider row.
3. In **Workload identity target**, enter the vendor ids of the provider:
   - Anthropic, from the Anthropic Console: `{"organization_id": "...",
     "federation_rule_id": "...", "service_account_id": "...",
     "workspace_id": "..."}`. `workspace_id` is necessary only when the
     rule has more than one workspace.
   - OpenAI, from the OpenAI dashboard: `{"identity_provider_id": "...",
     "service_account_id": "..."}`. The OpenAI identity provider must use
     the audience `https://api.openai.com/v1`. See the
     [plugin README](https://github.com/AWeber-Imbi/imbi/tree/main/plugins/openai).
4. Click **Use workload identity**. The provider row shows
   **Workload identity**.

Imbi mints a new token for each identity JWT and renews it before it
expires. Each token carries the tags `imbi_org` and `imbi_ai_provider`, so
the vendor can track cost for each provider. Model discovery uses the
token. To stop, click **Stop using workload identity**.

You need `ai_model:credentials`, membership of the organization, and
`secret_provider:write` in that organization.

### Imbi services

imbi-api, the assistant, and the Slack bot can use an Anthropic provider
with workload identity instead of `ANTHROPIC_API_KEY`. Set these
variables on imbi-api to the id of the provider:

| Variable | Service |
|---|---|
| `IMBI_AI_PROVIDER_API` | imbi-api (release notes and other completions) |
| `IMBI_AI_PROVIDER_ASSISTANT` | imbi-assistant |
| `IMBI_AI_PROVIDER_SLACKBOT` | imbi-slackbot |

The assistant and the Slack bot get the token from imbi-api as their own
service account (`imbi-assistant`, `imbi-slackbot`). Set
`IMBI_ASSISTANT_API_TOKEN` or `IMBI_SLACKBOT_API_TOKEN` on the service to
the API key of that account; see
[Imbi service accounts](service-accounts.md#imbi-service-accounts). With
the API key set, the service ignores `ANTHROPIC_API_KEY`. Without it, the
service uses `ANTHROPIC_API_KEY` as before.

imbi-api gives a service only the token of its own provider. The request
names no provider.

## Add a model manually

Click **Add model**, or click the plus icon on a provider row. The dialog has
two steps.

### Step 1: identity

| Field | Meaning |
|---|---|
| Provider | The provider that serves this model. Required. |
| Model name or URL | The identifier Imbi sends to the provider, such as `claude-sonnet-4-5`. A self-hosted gateway accepts a full inference URL. Required. |
| Display name | What engineers see in the model picker. Defaults to the model identifier. |
| Model type | `Generative` (returns text) or `Decision` (returns typed judgments and probabilities). The driver sets the default; TypeSafe allows only `Decision`, every other driver only `Generative`. |
| Interface | `Chat` or `Completion`. Generative models only. |

### Step 2: limits, cost, and access

| Field | Meaning |
|---|---|
| Context window | Maximum input tokens the model accepts. |
| Max output tokens | Maximum tokens the model returns in one response. |
| Input cost / 1M tokens | USD per one million input tokens. |
| Output cost / 1M tokens | USD per one million output tokens. |
| Default temperature | Between 0 and 2. Generative models only. |
| Default top_p | Between 0 and 1. Generative models only. |
| Monthly spend cap | USD per month. |
| Allowed teams | See [Team access](#team-access). |
| Enable immediately | Makes the model selectable as soon as it is created. |

Every field in step 2 is optional. Leave a cost empty when the price is
unknown or set by contract. Enter `0` for a self-hosted model.

!!! warning
    **Monthly spend cap is advisory.** Imbi does not block calls at the cap.
    The field records the number for a human to act on. Agent usage uses the
    model prices to calculate cost. See
    [Agents > Usage](agents.md#usage).

Two rules apply within the catalog. A model's display name must produce a slug
that is unique in the catalog. A model identifier must be unique within
its provider. Imbi returns `409` when either rule fails.

## Discover and import models

Anthropic, OpenAI, and OpenAI-compatible providers can report their own model
lists. Use this instead of typing model identifiers by hand.

1. Set a credential on the provider.
2. Click the refresh icon on the provider row. You can also expand the
   provider and click **Import from** that provider.
3. Wait for the list. Imbi calls the provider with its stored key.
4. Search the list, or click **Select all new**.
5. Select the models to add. A model already in the catalog shows an
   **Already configured** badge and cannot be selected.
6. Click **Import** in the footer.

Discovery reads only. Nothing is written until you import.

Every imported model lands enabled, as `Chat`, and available to every team.
Anthropic also supplies the context window and the maximum output tokens where
it publishes them. Imbi fills each price that the
[LiteLLM price file](#sync-prices-from-litellm) has. If Imbi cannot download
that file, the import continues without prices. Narrow the access and fill in
the missing costs afterwards.

Discovery also tests the stored credential. A failure reports the driver and
the HTTP status or the transport error. The provider's response body is never
shown, because a provider can echo the key back inside it.

Discovery fails with a clear message in three cases. The provider has no
stored credential. The driver does not support discovery. The provider
rejected the call.

## Sync prices from LiteLLM

The Anthropic and OpenAI model lists contain no prices. Imbi can copy list
prices from the public
[LiteLLM price file](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json).
The sync sets the input, output, cache read, and cache write prices.

1. Click **Sync prices** above the provider list.
2. Wait for the comparison. Imbi downloads the price file and shows only
   the prices that differ: the current price, then the LiteLLM price. The
   dialog counts the models that are up to date.
3. To replace a price that is already set, select **Overwrite set prices**
   for that model.
4. Click **Apply** in the footer.

Imbi fills an empty price. Imbi keeps a set price that differs, unless you
select overwrite for that model. Contract rates can differ from list prices,
so overwrite is off by default.

Imbi finds a model in the file by its model identifier. For the Anthropic and
OpenAI drivers, Imbi also tries `<driver>/<model identifier>`. The dialog
lists the models that have no match. Set their prices by hand.

The sync needs `ai_model:update`. The API routes are
`POST /ai-models/price-sync/preview` and `POST /ai-models/price-sync/apply`.

## Team access

A model is available either to every team or to named teams.

- **All teams** makes the model available to every team in every
  organization. This is the default.
- **Selecting one or more teams** restricts the model to those teams.

Select the **All teams** chip to return to access for every team. The team
picker lists the teams of the organization you have selected. A
restricted model must name at least one team. Imbi rejects an empty team list
with `422`.

Deleting a team does not update the models that name it. Review restricted
models after you delete a team.

## Enable and disable

Every provider and every model carries an enabled flag.

Use the switch on a model row to enable or disable it. A disabled model keeps
its configuration and disappears from every picker. Disable a model instead of
deleting it when you plan to bring it back.

## Delete

Expand the provider, click the edit icon on the model row, click **Continue**,
then click **Delete model**.

To delete a provider, click the edit icon on the provider row, then click
**Delete provider**. The button is disabled while the provider still serves
models. The API (`DELETE /ai-providers/{id}`) returns `409` for the same
condition. Delete the models first, or move them to another provider. There
is no cascade, so a provider cannot take its models with it.

## Permissions

| Permission | Grants |
|---|---|
| `ai_model:read` | View providers, models, and the driver list. |
| `ai_model:create` | Add providers and models. Run discovery and import discovered models. |
| `ai_model:update` | Change a provider or a model, including the enabled flag. Sync prices from LiteLLM. |
| `ai_model:delete` | Delete providers and models. |
| `ai_model:credentials` | Set and remove provider credentials. |
| `ai_provider:token` | Get the token of the AI provider of the calling service. The `imbi-assistant`, `imbi-slackbot`, and `admin` roles have it. |

Administrators hold all six. The Developer, Default, and Read Only roles hold
`ai_model:read`.

`POST /ai-providers/token` needs a service account with a configured
provider. A human administrator passes the permission check but gets `404`.
This is expected, not a fault.

`ai_model:credentials` is deliberately separate from `ai_model:update`.
Changing a model's temperature must not imply the right to replace the
production key.

See [Roles and Permissions](roles-and-permissions.md) to grant these to a
custom role.

## Related

- [ADR 0018: AI Model Catalog](../api/adr/0018-ai-model-catalog.md) records the
  design and the alternatives that were rejected.
- [API Configuration](../api/configuration.md) covers the API service settings.
