"""Imbi GitHub plugin (Architecture v3).

One :class:`~imbi.plugins.github.plugin.GitHubPlugin` backs every GitHub
Integration. The registry discovers this package by its ``imbi_plugin_*``
name and reads the module-level :data:`PLUGIN` attribute.
"""

from imbi.plugins.github.plugin import GitHubPlugin

#: The package's single plugin, discovered by the registry convention scan.
PLUGIN = GitHubPlugin

__all__ = ['PLUGIN', 'GitHubPlugin']
