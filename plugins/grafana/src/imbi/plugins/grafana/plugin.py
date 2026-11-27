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
plugin declares an empty action catalog. The lifecycle capability writes
the ``EXISTS_IN`` edge whose identifier (`{slug}-{id}` by default)
the alert rules carry in one label, so the gateway can route a delivery
to its project; the analysis capability repairs that edge. The webhook
capability lets a Grafana webhook be bound to an Integration and its
deliveries verified: when the
contact point's **HMAC signature** is on, Grafana sends the hex
HMAC-SHA256 of the raw body, keyed by the shared secret, in the
``X-Grafana-Alerting-Signature`` header. Leave the contact point's
**Timestamp Header** empty: with it set, Grafana signs
``<timestamp>:<body>`` instead, which the gateway does not compute.
"""

from imbi.common import plugins
from imbi.common.plugins.base import WebhookSignature
from imbi.plugins.grafana import links
from imbi.plugins.grafana.doctor import GrafanaDoctor
from imbi.plugins.grafana.lifecycle import GrafanaLifecycle
from imbi.plugins.grafana.steps import GrafanaSteps

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
            'Link each project to the Grafana alert rules that carry its '
            'slug in a label, receive Grafana Alerting webhook deliveries, '
            'verify their HMAC signature, and record each notification '
            'against its project.'
        ),
        auth_type='api_token',
        # A gateway delivery finds its project by the label value.
        shareable_service_identifier=False,
        options=[
            plugins.PluginOption(
                name='service_url',
                label='Grafana URL',
                description=(
                    'Base URL of Grafana, for example '
                    'https://grafana.example.com. Used for the alert rules '
                    'link of each project.'
                ),
                type='string',
                required=True,
            ),
            plugins.PluginOption(
                name='label',
                label='Project label',
                description=(
                    'The alert rule label that names the project. Each '
                    'alert rule must carry this label with the project '
                    'identifier (`{slug}-{id}` by default), and the '
                    'webhook Identifier Selector must read it, for example '
                    '`/commonLabels/service`.'
                ),
                type='string',
                default=links.DEFAULT_LABEL,
            ),
        ],
        credentials=[
            plugins.CredentialField(
                name='api_token',
                label='Service Account Token',
                description=(
                    'A Grafana service account token with the Viewer '
                    'role. The workflow steps and the live doctor checks '
                    'use it.'
                ),
                required=False,
            ),
        ],
        capabilities=[
            plugins.Capability(
                kind='lifecycle',
                label='Project lifecycle',
                description=(
                    'Link each project to its Grafana alert rules when it '
                    'is created or updated, and remove the link when it is '
                    'deleted.'
                ),
                hints={
                    'supports_lifecycle_sync': True,
                    'lifecycle_events': ['created', 'updated', 'deleted'],
                },
                handler=GrafanaLifecycle,
            ),
            plugins.Capability(
                kind='webhook-actions',
                label='Webhook actions',
                description=(
                    'Receives Grafana Alerting webhook deliveries. The '
                    'gateway records each as an event; the capability '
                    'advertises no actions.'
                ),
                handler=GrafanaWebhookActions,
            ),
            plugins.Capability(
                kind='analysis',
                label='Project doctor',
                description=(
                    'Check that the project is linked to Grafana with the '
                    'identifier its alert rules carry, with a one-click '
                    'repair. With the token, also check that alert rules '
                    'and dashboards carry the identifier.'
                ),
                handler=GrafanaDoctor,
            ),
            plugins.Capability(
                kind='workflow-steps',
                label='Workflow steps',
                description=(
                    'Workflow steps that read Prometheus metrics: gather '
                    'metrics, and a metric threshold gate. A query can use '
                    '$project for the project identifier.'
                ),
                project_scoped=False,
                handler=GrafanaSteps,
            ),
        ],
    )
