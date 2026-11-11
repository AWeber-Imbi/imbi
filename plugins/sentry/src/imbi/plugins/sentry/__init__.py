from importlib import metadata

from imbi.plugins.sentry.plugin import SentryPlugin

#: Discovered by the imbi-common registry's convention scan.
PLUGIN = SentryPlugin

version = metadata.version('imbi-plugin-sentry')
__all__ = ['PLUGIN', 'SentryPlugin', 'version']
