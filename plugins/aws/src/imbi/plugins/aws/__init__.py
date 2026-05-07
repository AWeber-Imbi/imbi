"""AWS plugins for Imbi.

Ships three plugin entry points from a single distribution:

* ``aws-iam-ic`` -- :class:`IdentityPlugin` for AWS IAM Identity Center.
* ``aws-ssm`` -- :class:`ConfigurationPlugin` backed by SSM Parameter
  Store.
* ``aws-cloudwatch-logs`` -- :class:`LogsPlugin` backed by CloudWatch
  Logs Insights.

The data plugins consume credentials from a flat ``dict[str, str]``
populated by either the ``ServiceApplication`` static-key path or the
identity-hydrated path that calls ``aws-iam-ic.materialize()``;
neither plugin needs to know which source applied.
"""

from imbi_plugin_aws.cloudwatch import CloudWatchLogsPlugin
from imbi_plugin_aws.identity import AwsIamIcPlugin
from imbi_plugin_aws.ssm import SsmPlugin

__all__ = ['AwsIamIcPlugin', 'CloudWatchLogsPlugin', 'SsmPlugin']
