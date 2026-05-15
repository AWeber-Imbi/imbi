from importlib import metadata

from imbi_plugin_sonarqube.plugin import SonarqubePlugin

version = metadata.version('imbi-plugin-sonarqube')
__all__ = ['SonarqubePlugin', 'version']
