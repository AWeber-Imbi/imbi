"""Sentry plugin (Plugin Architecture v3)."""

from imbi.common import plugins
from imbi.common.plugins.base import WebhookSignature
from imbi.plugins.sentry import client
from imbi.plugins.sentry.doctor import SentryDoctor
from imbi.plugins.sentry.lifecycle import SentryLifecycle


class SentryWebhookActions(plugins.WebhookActionsCapability):
    """Sentry integration-platform webhooks, routed by project slug."""

    @classmethod
    def actions(cls) -> list[plugins.ActionDescriptor]:
        return [
            plugins.ActionDescriptor.model_validate(
                {
                    'name': 'sync_issue_counts',
                    'label': 'Sync Sentry issue counts',
                    'description': (
                        'Counts the Sentry issues that match each search in '
                        'the issue_count_facts option and patches the '
                        'matching project facts.'
                    ),
                    'callable': (
                        'imbi.plugins.sentry.actions:sync_issue_counts'
                    ),
                    'config_model': (
                        'imbi.plugins.sentry.actions:SyncIssueCountsConfig'
                    ),
                }
            )
        ]

    @classmethod
    def signature(cls) -> WebhookSignature:
        # Hex HMAC-SHA256 of the raw body, keyed by the Sentry internal
        # integration's client secret, with no prefix.
        return WebhookSignature(
            header='sentry-hook-signature', prefix='', secret='webhook'
        )


class SentryPlugin(plugins.Plugin):
    """Sentry integration plugin."""

    manifest = plugins.PluginManifest.model_validate(
        {
            'slug': 'sentry',
            'name': 'Sentry',
            'icon': 'si-sentry',
            'description': (
                'Create and link a Sentry project for each project, and keep '
                'issue-count facts in sync from Sentry webhooks and the '
                'Project Doctor.'
            ),
            'auth_type': 'api_token',
            'options': [
                {
                    'name': 'service_url',
                    'label': 'Sentry URL',
                    'description': (
                        'Base URL of Sentry. Leave blank for '
                        'https://sentry.io.'
                    ),
                    'type': 'string',
                },
                {
                    'name': 'organization',
                    'label': 'Sentry organization slug',
                    'type': 'string',
                    'required': True,
                },
                {
                    'name': 'team_mapping',
                    'label': 'Team to Sentry team',
                    'description': (
                        'Maps an Imbi team slug to the Sentry team that owns '
                        "the team's new Sentry projects. An unmapped team "
                        'uses its own slug.'
                    ),
                    'type': 'mapping',
                },
                {
                    'name': 'issue_count_facts',
                    'label': 'Issue-count facts',
                    'description': (
                        'Maps a project fact name to the Sentry issue search '
                        'whose count it holds, e.g. `sentry_open_issues` to '
                        '`is:unresolved`. Each fact must exist as an integer '
                        'property in a project blueprint.'
                    ),
                    'type': 'mapping',
                    'default': client.DEFAULT_ISSUE_COUNT_FACTS,
                },
                {
                    'name': 'issue_period',
                    'label': 'Issue search period',
                    'description': (
                        'Sentry statsPeriod the counts cover, e.g. `14d` or '
                        '`90d`. The issues link uses the same period.'
                    ),
                    'type': 'string',
                    'default': client.DEFAULT_ISSUE_PERIOD,
                },
            ],
            'credentials': [
                {
                    'name': 'auth_token',
                    'label': 'Sentry auth token',
                    'description': (
                        'Token of a Sentry internal integration with '
                        'Project: Admin (to create projects) and Issue & '
                        'Event: Read.'
                    ),
                }
            ],
            'capabilities': [
                {
                    'kind': 'lifecycle',
                    'label': 'Project lifecycle',
                    'description': (
                        'Create (or link) a Sentry project when a project '
                        'is created.'
                    ),
                    'hints': {'lifecycle_events': ['created']},
                    'handler': SentryLifecycle,
                },
                {
                    'kind': 'webhook-actions',
                    'label': 'Webhook actions',
                    'description': (
                        'Sentry issue webhooks dispatched by imbi-gateway.'
                    ),
                    'handler': SentryWebhookActions,
                },
                {
                    'kind': 'analysis',
                    'label': 'Project doctor',
                    'description': (
                        'Validate the Sentry project link and issue-count '
                        'facts against Sentry, with one-click repairs.'
                    ),
                    'handler': SentryDoctor,
                },
            ],
        }
    )
