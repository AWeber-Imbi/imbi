"""A valid fixture plugin used by registry discovery tests.

Exposes a module-level ``PLUGIN`` (convention discovery) and an
``ExplicitPlugin`` alias (``IMBI_PLUGINS`` discovery).
"""

import pydantic

from imbi.common.plugins import base


class SampleActionConfig(pydantic.BaseModel):
    pass


async def sample_action(
    *, ctx, credentials, external_identifier, action_config, event
) -> None:
    del ctx, credentials, external_identifier, action_config, event


class FixtureConfiguration(base.ConfigurationCapability):
    async def list_keys(self, ctx, credentials):
        return []

    async def get_values(self, ctx, credentials, keys=None):
        return []

    async def set_value(self, ctx, credentials, key, value):
        return base.ConfigKey(key=key, data_type='string')

    async def delete_key(self, ctx, credentials, key):
        return None


class FixtureWebhookActions(base.WebhookActionsCapability):
    @classmethod
    def actions(cls):
        return [
            base.ActionDescriptor(
                name='do_thing',
                label='Do Thing',
                callable=(  # type: ignore[arg-type]
                    'libraries.common.tests.test_plugins.fixtures.good_plugin:sample_action'
                ),
                config_model=(  # type: ignore[arg-type]
                    'libraries.common.tests.test_plugins.fixtures.good_plugin'
                    ':SampleActionConfig'
                ),
            )
        ]


class GoodPlugin(base.Plugin):
    manifest = base.PluginManifest(
        slug='good',
        name='Good Plugin',
        capabilities=[
            base.Capability(
                kind='configuration',
                label='Configuration',
                handler=FixtureConfiguration,
            ),
            base.Capability(
                kind='webhook-actions',
                label='Webhook Actions',
                handler=FixtureWebhookActions,
            ),
        ],
    )


PLUGIN = GoodPlugin
ExplicitPlugin = GoodPlugin
