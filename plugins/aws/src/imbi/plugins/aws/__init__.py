"""AWS plugins for Imbi.

Phase 1 ships the IAM Identity Center identity plugin
(``aws-iam-ic``).  ``aws-ssm`` (configuration) and
``aws-cloudwatch-logs`` (logs) entry points will land in follow-up
PRs that consume :class:`imbi_common.plugins.PluginContext.identity`
when an assignment names this package's identity plugin.
"""

from imbi_plugin_aws.identity import AwsIamIcPlugin

__all__ = ['AwsIamIcPlugin']
