"""The Anthropic plugin manifest.

The plugin has no Integration capability. It adds the ``anthropic_wif``
secret provider and the Anthropic token exchanger (for AI Providers).
"""

import imbi.common.plugins as plugins
from imbi.plugins.anthropic import wif


class AnthropicPlugin(plugins.Plugin):
    manifest = plugins.PluginManifest(
        slug='anthropic',
        name='Anthropic',
        description='Anthropic workload identity federation for model calls',
        icon='si-anthropic',
        auth_type='none',
        capabilities=[],
        secret_providers=[wif.AnthropicWif],
        token_exchangers=[wif.AnthropicExchanger],
    )
