"""Imbi OIDC identity plugin."""

from imbi.plugins.oidc.plugin import OIDCIdentity, OIDCPlugin

PLUGIN = OIDCPlugin

__all__ = ['PLUGIN', 'OIDCIdentity', 'OIDCPlugin']
