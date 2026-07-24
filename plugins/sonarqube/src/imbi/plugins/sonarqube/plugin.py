"""SonarQube plugin (Plugin Architecture v3).

The package ships one :class:`SonarQubePlugin` whose manifest declares the
SonarQube server URL as an integration-level option, the API token as the
integration's only credential, a ``webhook-actions`` capability that
catalogs the ``update_project_from_webhook`` action, and an ``analysis``
capability (the project doctor) that validates and repairs the project's
SonarQube component binding.
"""

import logging

from imbi.common import plugins
from imbi.plugins.sonarqube.doctor import SonarQubeDoctor

LOGGER = logging.getLogger(__name__)


class SonarQubeWebhookActions(plugins.WebhookActionsCapability):
    """SonarQube ``webhook-actions`` capability.

    Declares a single webhook action -- ``update_project_from_webhook``
    -- via :meth:`actions`. The host (``imbi-gateway``) looks the plugin
    up by slug, picks the descriptor by action name, validates the rule's
    ``handler_config`` against
    :attr:`imbi.plugins.sonarqube.actions.MetricMappings`, and invokes the
    callable. The capability itself carries no dispatch logic.
    """

    @classmethod
    def actions(cls) -> list[plugins.ActionDescriptor]:
        return [
            plugins.ActionDescriptor.model_validate(
                {
                    'name': 'update_project_from_webhook',
                    'label': 'Update Project from SonarQube Measures',
                    'description': (
                        'Fetches the configured SonarQube measurements for '
                        "the webhook's component and patches the matching "
                        "Imbi project's facts with the returned values."
                    ),
                    'callable': (
                        'imbi.plugins.sonarqube.actions:update_project_from_webhook'
                    ),
                    'config_model': (
                        'imbi.plugins.sonarqube.actions:MetricMappings'
                    ),
                }
            ),
        ]


class SonarQubePlugin(plugins.Plugin):
    """SonarQube integration plugin."""

    manifest = plugins.PluginManifest.model_validate(
        {
            'slug': 'sonarqube',
            'name': 'SonarQube',
            'icon': 'si-sonarqubeserver',
            'description': (
                'Fetches SonarQube measurements on demand from the gateway '
                "webhook pipeline and patches the matching Imbi project's "
                'facts.'
            ),
            'auth_type': 'api_token',
            'options': [
                {
                    'name': 'service_url',
                    'label': 'SonarQube URL',
                    'description': (
                        'Base URL of the SonarQube server, e.g. '
                        'https://sonarqube.example.com.'
                    ),
                    'type': 'string',
                    'required': True,
                }
            ],
            'credentials': [
                {
                    'name': 'api_token',
                    'label': 'SonarQube user token',
                    'description': (
                        'A SonarQube **user** token (My Account > Security '
                        'in SonarQube), which is prefixed `squ_`. Analysis '
                        'tokens -- `sqa_` (global) and `sqp_` (project) -- '
                        'are scoped to scanner endpoints and return 403 on '
                        'every call this plugin makes, no matter what '
                        'permissions the issuing account holds. The token '
                        'needs Browse on the projects being read, plus '
                        'Create Projects if the Project Doctor should create '
                        'missing SonarQube projects.'
                    ),
                }
            ],
            'capabilities': [
                {
                    'kind': 'webhook-actions',
                    'label': 'Webhook actions',
                    'description': (
                        'SonarQube webhook actions dispatched by imbi-gateway.'
                    ),
                    'handler': SonarQubeWebhookActions,
                },
                {
                    'kind': 'analysis',
                    'label': 'Project doctor',
                    'description': (
                        'Validate the SonarQube project component '
                        '(EXISTS_IN edge) against the live API and offer a '
                        'one-click search-and-create repair.'
                    ),
                    'handler': SonarQubeDoctor,
                },
            ],
        }
    )
