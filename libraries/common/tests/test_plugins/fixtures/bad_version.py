"""A plugin declaring an unsupported api_version (skipped at load)."""

from imbi.common.plugins import base
from libraries.common.tests.test_plugins.fixtures.good_plugin import (
    FixtureConfiguration,
)


class BadVersionPlugin(base.Plugin):
    manifest = base.PluginManifest(
        slug='bad-version',
        name='Bad Version Plugin',
        api_version=3,
        capabilities=[
            base.Capability(
                kind='configuration',
                label='Configuration',
                handler=FixtureConfiguration,
            ),
        ],
    )


PLUGIN = BadVersionPlugin
