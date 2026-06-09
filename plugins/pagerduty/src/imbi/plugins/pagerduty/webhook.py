"""PagerDuty webhook plugin (v1 stub).

PagerDuty incident events are captured by the gateway's built-in event
recording, driven entirely by the ``pagerduty`` ThirdPartyService
selectors (``identifier_selector`` / ``event_type_selector``) -- no
custom action is required for v1. This plugin therefore advertises an
empty action catalog. It exists so the webhook plugin instance is
present as the home for future event-triggered side effects (e.g.
enriching an "active incident" project fact or kicking a workflow)
without a later package-shape change.
"""

from __future__ import annotations

from imbi_common.plugins.base import (
    ActionDescriptor,
    CredentialField,
    PluginManifest,
    WebhookActionPlugin,
)


class PagerDutyWebhookPlugin(WebhookActionPlugin):
    """Webhook plugin for PagerDuty; no actions in v1."""

    manifest = PluginManifest(
        slug='pagerduty-webhook',
        name='PagerDuty Webhook',
        description=(
            'Receives PagerDuty incident webhooks. v1 records events via '
            'the gateway and advertises no custom actions.'
        ),
        plugin_type='webhook',
        auth_type='api_token',
        credentials=[
            CredentialField(
                name='api_key',
                label='PagerDuty REST API key',
                description='Shared with the other PagerDuty plugins.',
                required=False,
            )
        ],
    )

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return []
