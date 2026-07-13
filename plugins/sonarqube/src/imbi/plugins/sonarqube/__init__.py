from importlib import metadata

from imbi_plugin_sonarqube.plugin import SonarQubePlugin

#: Discovered by the imbi-common registry's convention scan.
PLUGIN = SonarQubePlugin

version = metadata.version('imbi-plugin-sonarqube')
__all__ = ['PLUGIN', 'SonarQubePlugin', 'version']
