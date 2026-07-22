"""Imbi OIDC identity plugin."""

from imbi_plugin_oidc.plugin import OIDCIdentity, OIDCPlugin

PLUGIN = OIDCPlugin

__all__ = ['PLUGIN', 'OIDCIdentity', 'OIDCPlugin']
