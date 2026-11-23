"""The Grafana plugin (Plugin Architecture v3).

A Grafana Alerting *webhook contact point* posts one request for each
notification group. The default body carries ``receiver``, ``status``
(``firing`` or ``resolved``), ``alerts`` (each with ``labels``,
``annotations``, ``startsAt``, ``endsAt``, ``values``, ``generatorURL``,
``fingerprint``, and ``silenceURL``), ``groupLabels``, ``commonLabels``,
``commonAnnotations``, ``externalURL``, ``groupKey``, ``title``,
``state``, and ``message``.

The gateway's built-in event recording captures each delivery, driven by
the Webhook's selectors (identifier, event type, user subject), so this
plugin declares an empty action catalog. It exists so a Grafana webhook
can be bound to an Integration and its deliveries verified: when the
contact point's **HMAC signature** is on, Grafana sends the hex
HMAC-SHA256 of the raw body, keyed by the shared secret, in the
``X-Grafana-Alerting-Signature`` header. Leave the contact point's
**Timestamp Header** empty: with it set, Grafana signs
``<timestamp>:<body>`` instead, which the gateway does not compute.
"""

from imbi.common import plugins
from imbi.common.plugins.base import WebhookSignature

#: The default Grafana HMAC signature header, lower case.
SIGNATURE_HEADER = 'x-grafana-alerting-signature'
#: Grafana sends the bare hex digest with no prefix.
SIGNATURE_PREFIX = ''


class GrafanaWebhookActions(plugins.WebhookActionsCapability):
    """Webhook-actions capability for Grafana; it has no actions."""

    @classmethod
    def actions(cls) -> list[plugins.ActionDescriptor]:
        return []

    @classmethod
    def signature(cls) -> WebhookSignature:
        # Grafana HMAC signature: hex HMAC-SHA256 of the raw body keyed
        # by the contact point's shared secret, stored as the
        # Webhook.secret. No timestamp header, so the hmac-hex scheme.
        return WebhookSignature(
            header=SIGNATURE_HEADER,
            prefix=SIGNATURE_PREFIX,
            secret='webhook',
        )


class GrafanaPlugin(plugins.Plugin):
    """Grafana Integration: receive alerting webhook deliveries."""

    manifest = plugins.PluginManifest(
        slug='grafana',
        name='Grafana',
        icon='si-grafana',
        description=(
            'Receive Grafana Alerting webhook deliveries, verify their '
            'HMAC signature, and record each notification against its '
            'project.'
        ),
        auth_type='none',
        capabilities=[
            plugins.Capability(
                kind='webhook-actions',
                label='Webhook actions',
                description=(
                    'Receives Grafana Alerting webhook deliveries. The '
                    'gateway records each as an event; the capability '
                    'advertises no actions.'
                ),
                handler=GrafanaWebhookActions,
            )
        ],
    )
