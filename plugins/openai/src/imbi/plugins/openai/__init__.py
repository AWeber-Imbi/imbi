"""Imbi OpenAI plugin: workload identity federation."""

from imbi.plugins.openai.plugin import OpenAIPlugin
from imbi.plugins.openai.wif import OpenAIExchanger, OpenAIWif

PLUGIN = OpenAIPlugin

__all__ = ['PLUGIN', 'OpenAIExchanger', 'OpenAIPlugin', 'OpenAIWif']
