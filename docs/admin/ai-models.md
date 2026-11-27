# AI Models

The **AI Models** section holds the catalog of AI models Imbi may call. The catalog has two levels. A **provider** is one
configured endpoint, with its own credential. A **model** is one model that
provider serves.

Each organization has its own catalog. A provider, its credential, and its
models belong to one organization, and only that organization can see or use
them. A slug is unique in the organization, so two organizations can each have
a model `default-chat`. Use [Team access](#team-access) to limit a model to
some teams of the organization.

Open the section at **Admin > &lt;Org&gt; Admin > AI Models**. The API routes
are under `/organizations/{org_slug}/ai-providers` and
`/organizations/{org_slug}/ai-models`. You must be a member of the
organization, and the `ai_model:*` permissions of your role in that
organization apply. A provider or model of another organization gives `404`.

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
| AWS Bedrock | Not used | API key, or the runtime IAM role | Yes |
| Google Vertex AI | Not used | API key, or the runtime IAM role | Yes, if the key is allowed |
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
4. Enter the base URL. Leave it empty to use the driver default, which the
   field shows as a hint. OpenAI-compatible requires a URL.
5. Enter the region for AWS Bedrock, or the region and project ID for Google
   Vertex AI.
6. Paste an API key. This field is optional. You can set the key later.
7. Enter a description. This field is optional.
8. Click **Create provider**.

The base URL must use `http` or `https`, must include a host, and must not
embed a username or a password. Imbi rejects any other URL. Imbi stores
the driver default as no base URL, and the provider row shows it with
`(default)`.

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

The identity source of the organization of the provider signs the tokens,
so each organization sets up its own. The organization needs an identity
source; see [Workload identity](secrets.md#workload-identity).

1. Click the key icon on the provider row.
2. In **Workload identity target**, enter the vendor ids of the provider:
   - Anthropic, from the Anthropic Console: `{"organization_id": "...",
     "federation_rule_id": "...", "service_account_id": "...",
     "workspace_id": "..."}`. `workspace_id` is necessary only when the
     rule has more than one workspace.
   - OpenAI, from the OpenAI dashboard: `{"identity_provider_id": "...",
     "service_account_id": "..."}`. The OpenAI identity provider must use
     the audience `https://api.openai.com/v1`. See the
     [plugin README](https://github.com/AWeber-Imbi/imbi/tree/main/plugins/openai).
3. Click **Use workload identity**. The provider row shows
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
variables on imbi-api to the provider, as `<org-slug>/<provider-slug>`
(for example `acme/anthropic`):

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

These variables set the credential of the configured model of the service
(`IMBI_ASSISTANT_MODEL`, `IMBI_SLACKBOT_MODEL`). When the model comes from
the catalog (a prompt version model or a default model), the service uses
the credential of the provider of that model, in this order:

1. The provider has a workload identity: the service asks imbi-api for a
   token of that provider, for the user of the call. This needs
   `IMBI_ASSISTANT_API_TOKEN` or `IMBI_SLACKBOT_API_TOKEN`. imbi-api gives
   the token only when the provider is an Anthropic provider in an
   organization of that user (else `403`). For the Slack bot, that
   organization must also be the organization of a Slack workspace.
2. Else `ANTHROPIC_API_KEY` of the service, sent to the base URL of the
   provider.
3. Else the call fails (`provider_credentials_unavailable`): the assistant
   returns `422`, and the Slack bot replies with an error.

A stored provider key never leaves imbi-api.

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
| Cache read cost / 1M tokens | USD per one million tokens read from the prompt cache. |
| Cache write (5m) cost / 1M tokens | USD per one million tokens written to the prompt cache with the 5-minute TTL. |
| Cache write (1h) cost / 1M tokens | USD per one million tokens written to the prompt cache with the 1-hour TTL. Agent usage prices 1-hour writes at this rate. |
| Default temperature | Between 0 and 2. Generative models only. |
| Default top_p | Between 0 and 1. Generative models only. |
| Structured output | The model can return JSON that matches a schema. See [Structured output](#structured-output). |
| Forced tool choice | Shown when **Structured output** is on. The model accepts a forced tool choice. See [Forced tool choice](#forced-tool-choice). |
| Monthly spend cap | USD per calendar month (UTC). See [Spend cap](#spend-cap). |
| Allowed teams | See [Team access](#team-access). |
| Enable immediately | Makes the model selectable as soon as it is created. |

Every field in step 2 is optional. Leave a cost empty when the price is
unknown or set by contract. Enter `0` for a self-hosted model.

Agent usage uses the model prices to calculate cost. See
[Reports > Agent Usage](agents.md#usage).

Two rules apply within the catalog. A model's display name must produce a slug
that is unique in the catalog. A model identifier must be unique within
its provider. Imbi returns `409` when either rule fails.

## Structured output

Set **Structured output** on a model that can return JSON that matches a
schema. A workflow [LLM Call step](workflows.md#llm-call) with output
fields can use only such a model. The switch is off by default, and
discovery does not set it, so set it on each model that supports it.

Imbi asks for the structured answer in the form of the driver:

| Driver | Form |
|---|---|
| Anthropic, AWS Bedrock | One `submit_result` tool call, forced unless [Forced tool choice](#forced-tool-choice) is off |
| OpenAI, OpenAI-compatible | A strict `json_schema` response format |
| Google Vertex AI | A JSON response schema (Gemini) |

Turn the switch off when the provider refuses the request. Imbi checks
the switch at two times:

- **Save.** Imbi does not save a workflow that has an LLM Call step
  with output fields on a model with the switch off. The `422` error
  says that the model does not support structured output.
- **Run.** When you turn the switch off after you save the workflow,
  the step fails at run time with `model_no_structured_output`.

### Forced tool choice

For Anthropic and AWS Bedrock, Imbi forces the model to call one tool,
`submit_result`. Some models refuse a forced tool choice, for example a
Claude model with extended thinking. The call then fails with
`model_unsupported`.

Turn **Forced tool choice** off for such a model. Imbi then sends the
tool with the tool choice `auto`, and adds an instruction to the
system prompt that tells the model to call the tool. Imbi checks the
answer against the schema. When the model does not call the tool, or
calls it more than one time, the call fails with `model_answer_invalid` and the step can try again. The
switch is on by default. Other drivers do not use it.

!!! note
    An LLM Call step on Google Vertex AI calls Gemini models only, and
    needs an API key on the provider. The runtime IAM role does not work
    for these calls.

## Discover and import models

Anthropic, OpenAI, OpenAI-compatible, AWS Bedrock, and Google Vertex AI
providers can report their own model lists. Use this instead of typing model
identifiers by hand.

AWS Bedrock lists the active text models of the provider's region. A model
with on-demand inference shows by its model ID. A model that you can call only
through a system inference profile, such as current Claude models, shows by
its profile ID (for example `us.anthropic.claude-...`). Without a stored key,
Imbi signs the calls with the runtime IAM role, which needs
`bedrock:ListFoundationModels` and `bedrock:ListInferenceProfiles`.

Google Vertex AI lists the Gemini publisher models with the stored key. The
express mode API reference does not include this method, so Google can refuse
it for an express mode key. Imbi then reports a 422 that tells you to add the
Gemini models by ID. Vertex discovery needs a stored key.

1. Set a credential on the provider (AWS Bedrock can use the IAM role).
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
The sync sets the input, output, cache read, cache write (5m), and cache
write (1h) prices.

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

The sync needs `ai_model:update`. It changes only the models of the
organization. The API routes are
`POST /organizations/{org_slug}/ai-models/price-sync/preview` and
`POST /organizations/{org_slug}/ai-models/price-sync/apply`.

## Team access

A model is available either to every team or to named teams.

- **All teams** makes the model available to every team of the
  organization. This is the default.
- **Selecting one or more teams** restricts the model to those teams.

Select the **All teams** chip to return to access for every team. The team
picker lists the teams of the organization. A team of another organization
gives `422`. A restricted model must name at least one team. Imbi rejects an
empty team list with `422`.

A prompt run (generative or decision) checks the teams of a restricted
model. A user must be a member of an allowed team. An LLM Call step of a workflow runs for the
owner team of the workflow, and only the workflows service can run it that
way. Otherwise the run fails with `403` (`model_not_allowed`). Admins can run
every model.

A workflow save checks the same rule. The model of an LLM Call step must allow
the owner team of the workflow, and the user who saves must be a member of an
allowed team. An admin does not need to be a member. Otherwise the save fails
with `403` (`model_not_allowed`).

An agent uses the model of its prompt version. The model must allow the owner
team of the agent:

- An agent save that changes the team or the prompt fails with `403`
  (`model_not_allowed`) when the team is not allowed. An agent without a
  pinned prompt version is not checked, because its tasks use the model of the
  runner.
- When a runner claims a task, Imbi checks the model id that the runner gets,
  because the catalog and the prompt label can change after the save. The task
  fails this check when no enabled catalog model has that model id, or every
  enabled catalog model with that model id is restricted to teams that do not
  include the owner team. A task that fails this check closes with
  `failed_external` (`model_not_allowed`) and does not run.
- A task without a prompt model uses the model of the runner
  (`IMBI_HARNESS_MODEL`, or the default of the agent CLI). The operator sets
  this model, so Imbi does not check it.

A model id is allowed for a user or a team when one enabled catalog model with
that model id is not restricted, or a restricted one includes the user or the
team. Prompt runs, workflows, agents, and agent tasks read only the catalog of
their organization.

Global prompts (such as the prompts of the assistant and the Slack bot) name a
model by slug. When you save a version of a global prompt, the slug must be a
model of some organization. A prompt run uses the model with that slug in the
organization of the run. The assistant and the Slack bot have no organization,
so they read the catalogs of the organizations of the user.

The assistant and the Slack bot use the model of their system prompt when the
prompt version names one. When the version names no model, they use the
default model of the organization when the user is a member of one
organization, else the configured model (`IMBI_ASSISTANT_MODEL` or
`IMBI_SLACKBOT_MODEL`). When the selected model cannot be used, Imbi does not
use another model: the assistant returns `403` (`model_not_allowed`) or `422`,
and the Slack bot replies with an error. Only an Anthropic model can be the model of
these system prompts. The assistant selects the
model when a conversation starts, and checks the selected model, also when it
is `IMBI_ASSISTANT_MODEL`. A non-admin gets `403` (`model_not_allowed`) when no
enabled catalog model allows the model id. `IMBI_ASSISTANT_MODEL` is allowed
only when no enabled catalog model has its model id. The assistant checks the
model of the conversation again on each message, because the allowed teams can
change. Admins can use every model.

Deleting a team does not update the models that name it. Review restricted
models after you delete a team.

## Default models

An organization and each of its teams can have one default model. A call
whose prompt or workflow step names no model uses the default. The order is:

1. The model of the prompt version, the prompt run, or the workflow step.
2. The default model of the team of the call.
3. The default model of the organization.
4. The model in the environment of the service.

The first level that names a model wins. When that model is disabled, its
provider is disabled, the caller may not use it, or it is at its
[spend cap](#spend-cap), the call fails. Imbi does
not try the next level. The environment model applies only when no level
names a model.

To set the organization default, select a model in **Default model** at the
top of the AI Models page. To set the team default, open the team in
**Teams** and select a model in **Default model**. Select **No model** to
clear a default.

A default model must be a generative model of the organization. A team
default must be a model that the team may use (see
[Team access](#team-access)). Imbi rejects other models with `422`.

A generative prompt run uses the defaults. A prompt run of a workflow step
uses the default of the owner team of the workflow, then the organization
default. The assistant and the Slack bot use the organization default when
the user is a member of one organization; they have no team. A decision
prompt and a Model decision step must name their model.

The assistant and the Slack bot call a catalog model with the credential of
its provider (see [Imbi services](#imbi-services)).

The API routes are `GET` and `PUT`
`/organizations/{org_slug}/default-ai-model` (`ai_model:read`,
`ai_model:update`) and `GET` and `PUT`
`/organizations/{org_slug}/teams/{slug}/default-ai-model` (`team:read`,
`team:update`). The body is `{"slug": "<model slug>"}`, or
`{"slug": null}` to clear the default.

## Spend cap

The spend of a model is the cost of its calls in the current calendar month
(UTC). Imbi adds the cost of each prompt run and of each agent usage report
of the model. A call with an unknown cost adds nothing. The AI Models page
shows the spend and the cap on each model row. The text is red when the spend
is at or over the cap.

When the spend of a model is at or over its **Monthly spend cap**, Imbi
refuses new calls to the model. It does not use another model in its place.

- A prompt run returns `422`.
- A Model decision step fails with `model_unavailable`.
- The assistant returns `422`, and the Slack bot replies with an error.
- An agent task closes with `exceeded_ceiling` (reason `spend_cap`) at the
  usage report that takes the spend to the cap.

Calls that are in progress are not counted until they end, so concurrent
calls can go over the cap by their cost. The spend starts again at zero on
the first day of each month (UTC). To use the model again in the same month,
increase the cap or clear it.

The spend counts only the calls made after the upgrade that added it. The
agent setting **Monthly cost cap** is different: it is per agent, and it is
advisory.

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
models. The API (`DELETE /organizations/{org_slug}/ai-providers/{id}`) returns `409` for the same
condition. Delete the models first, or move them to another provider. There
is no cascade, so a provider cannot take its models with it.

A model that is the default model of an organization or a team cannot be
deleted. `DELETE /organizations/{org_slug}/ai-models/{id}` returns `409` and
names the organizations and teams. Select another default first.

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
