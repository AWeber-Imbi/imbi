"""Imbi GitHub plugins.

A single connection plugin holds the flavor/host and shared App/PAT
credentials for the service; one host-agnostic plugin per behavior
(identity, deployment, lifecycle, commit-sync, pr-sync) reads the host
from that connection plugin.
"""

from imbi_plugin_github.connection import GitHubConnectionPlugin
from imbi_plugin_github.deployment import GitHubDeploymentPlugin
from imbi_plugin_github.identity import GitHubIdentityPlugin
from imbi_plugin_github.lifecycle import GitHubLifecyclePlugin

__all__ = [
    'GitHubConnectionPlugin',
    'GitHubDeploymentPlugin',
    'GitHubIdentityPlugin',
    'GitHubLifecyclePlugin',
]
