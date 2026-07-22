from importlib import metadata

from imbi.plugins.sonarqube.plugin import SonarQubePlugin

#: Discovered by the imbi-common registry's convention scan.
PLUGIN = SonarQubePlugin

version = metadata.version('imbi')
__all__ = ['PLUGIN', 'SonarQubePlugin', 'version']
