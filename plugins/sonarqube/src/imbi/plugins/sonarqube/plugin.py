"""SonarQube webhook-action plugin."""

import logging

from imbi_common.plugins import base as plugin_base

LOGGER = logging.getLogger(__name__)


class SonarqubePlugin(plugin_base.WebhookActionPlugin):
    """SonarQube webhook-action plugin.

    Declares a single webhook action -- ``update_project_from_webhook``
    -- via :meth:`actions`. The host (``imbi-gateway``) looks the
    plugin up by slug, picks the descriptor by action name, validates
    the rule's ``handler_config`` against
    :attr:`imbi_plugin_sonarqube.actions.MetricMappings`, and invokes
    the callable. The plugin class itself carries no dispatch logic.
    """

    manifest = plugin_base.PluginManifest.model_validate(
        {
            'slug': 'sonarqube',
            'name': 'SonarQube',
            'description': (
                'Fetches SonarQube measurements on demand from the gateway '
                "webhook pipeline and patches the matching Imbi project's "
                'facts.'
            ),
            'plugin_type': 'webhook',
            'credentials': [
                {
                    'name': 'api_token',
                    'label': 'SonarQube API Token',
                    'description': (
                        'User or analysis token with read access to '
                        '/api/measures/component.'
                    ),
                }
            ],
        }
    )

    @classmethod
    def actions(cls) -> list[plugin_base.ActionDescriptor]:
        return [
            plugin_base.ActionDescriptor.model_validate(
                {
                    'name': 'update_project_from_webhook',
                    'label': 'Update Project from SonarQube Measures',
                    'description': (
                        'Fetches the configured SonarQube measurements for '
                        "the webhook's component and patches the matching "
                        "Imbi project's facts with the returned values."
                    ),
                    'callable': (
                        'imbi_plugin_sonarqube.actions:update_project_from_webhook'
                    ),
                    'config_model': (
                        'imbi_plugin_sonarqube.actions:MetricMappings'
                    ),
                }
            ),
        ]
