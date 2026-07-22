"""AWS plugin for Imbi (Plugin Architecture v3).

Ships one :class:`~imbi_plugin_aws.plugin.AWSPlugin` whose manifest
declares the Integration-level options and IAM Identity Center credential
blob once, plus three capabilities: ``identity`` (IAM Identity Center),
``logs`` (CloudWatch Logs), and ``configuration`` (SSM Parameter Store).

The registry discovers this package by the ``imbi_plugin_*`` naming
convention and reads the module-level :data:`PLUGIN` attribute; there are
no ``imbi.plugins`` entry points.
"""

from imbi_plugin_aws.plugin import AWSPlugin

#: Discovered by the imbi-common plugin registry (convention scan).
PLUGIN = AWSPlugin

__all__ = ['PLUGIN', 'AWSPlugin']
