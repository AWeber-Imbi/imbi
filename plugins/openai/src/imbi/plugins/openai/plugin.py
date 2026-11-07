"""The OpenAI plugin manifest.

The plugin has no Integration capability. It adds the ``openai_wif``
secret provider and the OpenAI token exchanger (for AI Providers).
"""

import imbi.common.plugins as plugins
from imbi.plugins.openai import wif


class OpenAIPlugin(plugins.Plugin):
    manifest = plugins.PluginManifest(
        slug='openai',
        name='OpenAI',
        description='OpenAI workload identity federation for model calls',
        icon='si-openai',
        auth_type='none',
        capabilities=[],
        secret_providers=[wif.OpenAIWif],
        token_exchangers=[wif.OpenAIExchanger],
    )
