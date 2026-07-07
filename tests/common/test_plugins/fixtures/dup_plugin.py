"""A second valid plugin that reuses the ``good`` slug (duplicate test)."""

from imbi_common.plugins import base
from tests.test_plugins.fixtures.good_plugin import FixtureConfiguration


class DuplicatePlugin(base.Plugin):
    manifest = base.PluginManifest(
        slug='good',
        name='Duplicate Slug Plugin',
        capabilities=[
            base.Capability(
                kind='configuration',
                label='Configuration',
                handler=FixtureConfiguration,
            ),
        ],
    )


PLUGIN = DuplicatePlugin
