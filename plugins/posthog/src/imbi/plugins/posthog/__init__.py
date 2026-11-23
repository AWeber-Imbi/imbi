"""Imbi PostHog plugin: receive PostHog webhook deliveries."""

from importlib import metadata

from imbi.plugins.posthog.plugin import PostHogPlugin, PostHogWebhookActions

#: Discovered by the imbi-common registry's convention scan.
PLUGIN = PostHogPlugin

version = metadata.version('imbi-plugin-posthog')
__all__ = ['PLUGIN', 'PostHogPlugin', 'PostHogWebhookActions', 'version']
