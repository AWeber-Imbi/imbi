"""Imbi Anthropic plugin: workload identity federation."""

from imbi.plugins.anthropic.plugin import AnthropicPlugin
from imbi.plugins.anthropic.wif import AnthropicExchanger, AnthropicWif

PLUGIN = AnthropicPlugin

__all__ = ['PLUGIN', 'AnthropicExchanger', 'AnthropicPlugin', 'AnthropicWif']
