# Webhook Action Plugins

`WebhookActionPlugin` is the abstract base for plugins that react to
inbound webhook payloads. Declare `plugin_type='webhook'` in the
manifest. The host (typically `imbi-gateway`) receives the webhook,
resolves the matching project(s) from the payload, and routes each match
to a named **action**.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

## The action-catalog contract

A webhook plugin does not implement a dispatch method. Instead it
advertises a static catalog of actions via the `actions()` classmethod,
returning one `ActionDescriptor` per action. Each descriptor names the
action and points (via `pydantic.ImportString`) at:

- a **callable** — a module-level `async` function with the uniform
  signature described below, and
- a **config model** — a `pydantic.BaseModel` subclass the host uses to
  validate the rule's `handler_config` *before* dispatch and to render
  the rule editor from its JSON Schema.

The host parses `WebhookRule.handler` as `"<plugin_slug>#<action_name>"`,
looks the plugin up in the registry, selects the matching descriptor,
validates `handler_config` against `config_model`, and invokes
`callable`. The plugin class itself carries no runtime dispatch logic.

```python
# imbi_plugin_sonarqube/plugin.py
from imbi_common.plugins import (
    ActionDescriptor,
    CredentialField,
    PluginManifest,
    WebhookActionPlugin,
)


class SonarQubePlugin(WebhookActionPlugin):
    manifest = PluginManifest(
        slug='sonarqube',
        name='SonarQube',
        plugin_type='webhook',
        credentials=[
            CredentialField(name='api_token', label='SonarQube API Token'),
        ],
    )

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return [
            ActionDescriptor(
                name='update_project_from_webhook',
                label='Update project from webhook',
                description='Pull the latest analysis onto the project.',
                callable='imbi_plugin_sonarqube.actions'
                ':update_project_from_webhook',
                config_model='imbi_plugin_sonarqube.actions:UpdateConfig',
            ),
        ]
```

```python
# imbi_plugin_sonarqube/actions.py
import pydantic

from imbi_common.plugins import PluginContext


class UpdateConfig(pydantic.BaseModel):
    metric_keys: list[str] = ['coverage', 'bugs']


async def update_project_from_webhook(
    *,
    ctx: PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: UpdateConfig,
    event: object,
) -> None:
    ...
```

## The callable signature

The host invokes the action callable with keyword-only arguments:

- **`ctx`** — a `PluginContext` carrying the resolved project's identity
  plus any `assignment_options` the host shares (the gateway stashes
  `service_slug` / `service_endpoint` from the matched third-party
  service here).
- **`credentials`** — decrypted plugin credentials keyed by the
  manifest's `CredentialField.name`. Plugins that declare no credentials
  always receive `{}`; plugins *with* credentials are skipped (warning
  logged) when no `Plugin` node is attached to the matched service.
- **`external_identifier`** — the value the gateway resolved from
  `IMPLEMENTED_BY.identifier_selector` (e.g. a SonarQube `/project/key`
  JSON pointer); an empty string when not in play.
- **`action_config`** — a **pre-validated instance** of the action's
  `config_model`, never a raw JSON string. Operators set the underlying
  `handler_config` on the rule; the host validates and constructs the
  model before dispatching.
- **`event`** — the event context for the delivery, mirroring the
  project-independent fields of the `Event` row the host records:
  `type` (resolved event type, e.g. a GitHub `X-GitHub-Event`),
  `third_party_service` (service slug), `attributed_to` (resolved Imbi
  user, `''` when unattributed), `metadata.headers` (request headers,
  keys lower-cased and sensitive values redacted), and `payload` (the
  raw webhook body). `config_model` JSON-Pointer selectors resolve
  against this object, so the body lives under `/payload`; CEL
  expressions read `payload.<field>` (plus `type`, `metadata`, …). Most
  plugins rely on `ctx` and `external_identifier` instead.

## Rules of thumb

- Keep one action per public verb (`update_project_from_webhook`,
  `notify_release`, …) rather than overloading a single action with
  branching config. Action names become part of the operator-facing
  rule string (`sonarqube#update_project_from_webhook`) and benefit from
  being self-describing. Action `name` must match `^[a-z][a-z0-9_]*$`
  and be unique within the plugin; the registry rejects duplicates.
- Treat the host's "best effort" guarantee seriously: a call may run
  after a related `events`-table insert has failed, and the host will
  not retry on its own. Make actions idempotent so manual rerun is safe.
- Return a fresh list from `actions()` each call so callers can mutate
  the result safely. The host validates each descriptor's `callable` and
  `config_model` import strings at registry-load time, so misconfigured
  paths fail loud during load rather than at request time.

## API reference

::: imbi_common.plugins.WebhookActionPlugin

::: imbi_common.plugins.ActionDescriptor
