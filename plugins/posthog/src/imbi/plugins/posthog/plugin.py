"""The PostHog plugin (Plugin Architecture v3).

A PostHog *webhook destination* posts one request for each event that
passes its filters. The destination's body template is::

    {"event": "{event}", "person": "{person}"}

so a delivery is ``{"event": {...}, "person": {...}}``, where ``event``
carries ``uuid``, ``event``, ``distinct_id``, ``properties``,
``timestamp``, and ``url``, and ``person`` carries ``id``, ``name``,
``url``, and ``properties``.

The gateway's built-in event recording captures each delivery, driven by
the Webhook's selectors (identifier, event type, user subject), so this
plugin declares an empty action catalog. It exists so a PostHog webhook
can be bound to an Integration and its deliveries verified: PostHog
signs each request per the `Standard Webhooks
<https://www.standardwebhooks.com/>`_ specification, keyed by the
``Webhook.secret``.
"""

from imbi.common import plugins
from imbi.common.plugins.base import WebhookSignature

#: The Standard Webhooks signature header, lower case.
SIGNATURE_HEADER = 'webhook-signature'
#: The prefix of each symmetric (HMAC-SHA256) Standard Webhooks token.
SIGNATURE_PREFIX = 'v1,'


class PostHogWebhookActions(plugins.WebhookActionsCapability):
    """Webhook-actions capability for PostHog; it has no actions."""

    @classmethod
    def actions(cls) -> list[plugins.ActionDescriptor]:
        return []

    @classmethod
    def signature(cls) -> WebhookSignature:
        # Standard Webhooks: base64 HMAC-SHA256 of
        # ``<webhook-id>.<webhook-timestamp>.<body>``, keyed by the
        # ``whsec_`` secret the destination shows, stored as the
        # Webhook.secret.
        return WebhookSignature(
            header=SIGNATURE_HEADER,
            prefix=SIGNATURE_PREFIX,
            secret='webhook',
            scheme='standard-webhooks',
        )


class PostHogPlugin(plugins.Plugin):
    """PostHog Integration: receive webhook deliveries."""

    manifest = plugins.PluginManifest(
        slug='posthog',
        name='PostHog',
        icon='si-posthog',
        description=(
            'Receive PostHog webhook destination deliveries, verify their '
            'signature, and record each event against its project.'
        ),
        auth_type='none',
        capabilities=[
            plugins.Capability(
                kind='webhook-actions',
                label='Webhook actions',
                description=(
                    'Receives PostHog webhook deliveries. The gateway '
                    'records each as an event; the capability advertises '
                    'no actions.'
                ),
                handler=PostHogWebhookActions,
            )
        ],
    )
