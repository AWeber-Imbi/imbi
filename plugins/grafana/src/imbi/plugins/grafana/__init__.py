"""Imbi Grafana plugin: link projects to Grafana alert rules and
receive Grafana Alerting webhook deliveries."""

from importlib import metadata

from imbi.plugins.grafana.plugin import GrafanaPlugin, GrafanaWebhookActions

#: Discovered by the imbi-common registry's convention scan.
PLUGIN = GrafanaPlugin

version = metadata.version('imbi-plugin-grafana')
__all__ = ['PLUGIN', 'GrafanaPlugin', 'GrafanaWebhookActions', 'version']
