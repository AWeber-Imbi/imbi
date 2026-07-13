"""Imbi PagerDuty plugin.

A single :class:`~imbi_common.plugins.base.Plugin` declaring one
PagerDuty Integration with three capabilities: ``lifecycle`` (provision
and maintain a service), ``incidents`` (live-query the Incidents tab),
and ``webhook-actions`` (an empty v1 catalog). The REST API key
credential and the escalation-policy / gateway options are declared once
at the Integration level and shared by every capability.
"""

from imbi_common.plugins.base import (
    Capability,
    CredentialField,
    Plugin,
    PluginManifest,
    PluginOption,
)

from imbi_plugin_pagerduty.incidents import PagerDutyIncidents
from imbi_plugin_pagerduty.lifecycle import PagerDutyLifecycle
from imbi_plugin_pagerduty.webhook import PagerDutyWebhookActions

_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='team_escalation_policy_mapping',
        label='Team to escalation policy',
        description=(
            'Maps an Imbi team slug to the PagerDuty escalation policy id '
            "the team's services route to. A PagerDuty service requires "
            'an escalation policy, so a project whose team is unmapped is '
            'skipped with an operator message.'
        ),
        type='mapping',
        required=True,
    ),
    PluginOption(
        name='default_escalation_policy_id',
        label='Default escalation policy id',
        description='Fallback escalation policy for unmapped teams.',
        type='string',
        required=False,
    ),
    PluginOption(
        name='gateway_webhook_url',
        label='Gateway webhook URL',
        description=(
            'Public imbi-gateway notifications URL the per-service '
            'PagerDuty webhook subscription delivers to. Leave blank to '
            'skip webhook provisioning.'
        ),
        type='string',
        required=False,
    ),
]

_CREDENTIALS: list[CredentialField] = [
    CredentialField(
        name='api_key',
        label='PagerDuty REST API key',
        description='A REST API key with write access to services.',
        required=True,
    )
]


class PagerDutyPlugin(Plugin):
    """PagerDuty Integration: lifecycle, incidents, and webhook actions."""

    manifest = PluginManifest(
        slug='pagerduty',
        name='PagerDuty',
        icon='si-pagerduty',
        description=(
            'Provision and maintain a PagerDuty service for each project, '
            "routed to the owning team's escalation policy, surface the "
            "service's incidents on the Incidents tab, and receive incident "
            'webhooks back into Imbi.'
        ),
        auth_type='api_token',
        options=_OPTIONS,
        credentials=_CREDENTIALS,
        capabilities=[
            Capability(
                kind='lifecycle',
                label='Service lifecycle',
                description=(
                    'Provision and maintain a PagerDuty service for the '
                    'project with a per-service webhook subscription.'
                ),
                hints={
                    'supports_lifecycle_sync': True,
                    'lifecycle_events': [
                        'created',
                        'updated',
                        'deleted',
                        'relocated',
                    ],
                },
                handler=PagerDutyLifecycle,
            ),
            Capability(
                kind='incidents',
                label='Incidents',
                description=(
                    "Live-query PagerDuty for the project service's "
                    'incidents and render them on the Incidents tab.'
                ),
                hints={'cacheable': True},
                handler=PagerDutyIncidents,
            ),
            Capability(
                kind='webhook-actions',
                label='Webhook actions',
                description=(
                    'Receives PagerDuty incident webhooks. v1 records '
                    'events via the gateway and advertises no custom '
                    'actions.'
                ),
                handler=PagerDutyWebhookActions,
            ),
        ],
    )


PLUGIN = PagerDutyPlugin

__all__ = [
    'PLUGIN',
    'PagerDutyIncidents',
    'PagerDutyLifecycle',
    'PagerDutyPlugin',
    'PagerDutyWebhookActions',
]
