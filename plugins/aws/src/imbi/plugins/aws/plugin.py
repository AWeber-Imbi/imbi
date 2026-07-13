"""The single AWS plugin (Plugin Architecture v3).

One :class:`AWSPlugin` backs every AWS Integration. Its manifest declares
the Integration-level options (``region``, ``default_role_name``) and the
IAM Identity Center credential blob **once**, plus three capabilities:

* ``identity`` — AWS IAM Identity Center device-code federation, the
  credential mechanism for the Integration
  (:class:`~imbi_plugin_aws.identity.AWSIdentity`).
* ``logs`` — CloudWatch Logs Insights search
  (:class:`~imbi_plugin_aws.cloudwatch.CloudWatchLogs`).
* ``configuration`` — SSM Parameter Store
  (:class:`~imbi_plugin_aws.ssm.SSMConfiguration`).

The ``logs`` and ``configuration`` capabilities carry no static AWS
credentials: they set ``requires_identity`` and consume the STS keys the
identity capability materializes onto ``PluginContext.identity``.
"""

from __future__ import annotations

import imbi_common.plugins as plugins

from imbi_plugin_aws.cloudwatch import CloudWatchLogs
from imbi_plugin_aws.identity import (
    DEFAULT_SCOPES,
    REFRESH_SCOPE,
    AWSIdentity,
)
from imbi_plugin_aws.ssm import SSMConfiguration

_IDENTITY_WIDGET_TEXT = (
    'Connect to enable project level functionality such as '
    'configuration and log access.'
)

_ROLE_TEMPLATE_HELP = (
    'Supports ${project_slug}, ${org_slug}, ${team_slug}, '
    '${environment}, ${project_id}.'
)


class AWSPlugin(plugins.Plugin):
    """AWS Integration: IAM IC identity + CloudWatch logs + SSM config."""

    manifest = plugins.PluginManifest(
        slug='aws',
        name='AWS',
        icon='tabler-brand-aws',
        description=(
            'Amazon Web Services integration: IAM Identity Center '
            'federation, CloudWatch Logs, and SSM Parameter Store.'
        ),
        auth_type='aws-iam-ic',
        options=[
            plugins.PluginOption(
                name='region',
                label='AWS Region',
                type='string',
                required=True,
                description=(
                    'Default region for IAM Identity Center and the log / '
                    'parameter capabilities. A per-environment '
                    'AwsAccount.default_region overrides it.'
                ),
            ),
            plugins.PluginOption(
                name='default_role_name',
                label='Default IAM Role',
                type='string',
                required=False,
                description=(
                    'IAM role assumed when a per-environment AwsAccount '
                    'binding does not specify one of its own. '
                    + _ROLE_TEMPLATE_HELP
                ),
            ),
        ],
        credentials=[
            plugins.CredentialField(
                name='client_id',
                label='Cached IAM IC Client ID',
                description='Auto-managed via RegisterClient.',
                required=False,
            ),
            plugins.CredentialField(
                name='client_secret',
                label='Cached IAM IC Client Secret',
                description='Auto-managed via RegisterClient.',
                required=False,
            ),
            plugins.CredentialField(
                name='client_scopes',
                label='Cached IAM IC Client Scopes',
                description=(
                    f'Space-separated scopes the cached client was '
                    f'registered with. Auto-managed; absence (or a set '
                    f'that omits {REFRESH_SCOPE}) forces a fresh '
                    f'RegisterClient on the next connect so refresh '
                    f'tokens are issued.'
                ),
                required=False,
            ),
        ],
        capabilities=[
            plugins.Capability(
                kind='identity',
                label='AWS IAM Identity Center',
                description='Federated AWS access via IAM Identity Center.',
                default_enabled=True,
                project_scoped=False,
                requires_identity=False,
                hints={
                    'login_capable': True,
                    'default_scopes': DEFAULT_SCOPES,
                    'widget_text': _IDENTITY_WIDGET_TEXT,
                    'cacheable': False,
                },
                options=[
                    plugins.PluginOption(
                        name='start_url',
                        label='IAM IC Start URL',
                        type='string',
                        required=True,
                        description='e.g. https://example.awsapps.com/start',
                    ),
                    plugins.PluginOption(
                        name='default_account_id',
                        label='Default AWS Account ID',
                        type='string',
                        required=False,
                    ),
                ],
                handler=AWSIdentity,
            ),
            plugins.Capability(
                kind='logs',
                label='AWS CloudWatch Logs',
                description=(
                    'Search CloudWatch Logs from the Imbi project logs tab.'
                ),
                requires_identity=True,
                hints={'supports_histogram': True, 'cacheable': False},
                options=[
                    plugins.PluginOption(
                        name='log_group_names',
                        label='Log Group Names',
                        type='string',
                        required=True,
                        description=(
                            'Comma-separated list of log group selectors. '
                            'Supports ${project_slug}, ${org_slug}, '
                            '${environment}, ${project_id}. Each entry can '
                            'be: a literal name; a glob (`*` / `?` / '
                            '`[...]`); `regex:<pattern>` for an explicit '
                            'regex; or `prefix:<name>` for SOURCE-mode '
                            'prefix selection. Glob and regex entries page '
                            'DescribeLogGroups and match client-side (capped '
                            'at 50 results per query); `prefix:` entries use '
                            'CloudWatch SOURCE selection and may not be '
                            'combined with other entries (max 5).'
                        ),
                    ),
                    plugins.PluginOption(
                        name='base_filter',
                        label='Base Filter Expression',
                        type='string',
                        required=False,
                        description=(
                            'Logs Insights expression (without leading '
                            '"filter") applied as an additional must clause. '
                            'Supports the same template variables as Log '
                            'Group Names.'
                        ),
                    ),
                    plugins.PluginOption(
                        name='message_field',
                        label='Message Field',
                        type='string',
                        default='@message',
                    ),
                    plugins.PluginOption(
                        name='timestamp_field',
                        label='Timestamp Field',
                        type='string',
                        default='@timestamp',
                    ),
                    plugins.PluginOption(
                        name='level_field',
                        label='Level Field',
                        type='string',
                        default='level',
                    ),
                    plugins.PluginOption(
                        name='poll_interval_ms',
                        label='Poll Interval (ms)',
                        type='integer',
                        default=500,
                    ),
                    plugins.PluginOption(
                        name='timeout_seconds',
                        label='Query Timeout',
                        type='integer',
                        default=30,
                    ),
                ],
                handler=CloudWatchLogs,
            ),
            plugins.Capability(
                kind='configuration',
                label='AWS SSM Parameter Store',
                description=(
                    'Read and write project configuration as SSM parameters.'
                ),
                requires_identity=True,
                hints={'cacheable': False},
                options=[
                    plugins.PluginOption(
                        name='path_prefix',
                        label='Parameter Path Prefix',
                        type='string',
                        required=True,
                        description=(
                            "Path prefix under which this project's "
                            'parameters live. Supports ${project_slug}, '
                            '${org_slug}, ${environment}, ${project_id}. '
                            'Must start with /. Example: '
                            '/imbi/${environment}/${project_slug}/'
                        ),
                    ),
                    plugins.PluginOption(
                        name='kms_key_id',
                        label='KMS Key ID',
                        type='string',
                        required=False,
                        description=(
                            'KMS key id/alias for SecureString writes. '
                            'Defaults to alias/aws/ssm.'
                        ),
                    ),
                    plugins.PluginOption(
                        name='timeout_seconds',
                        label='Request Timeout',
                        type='integer',
                        default=15,
                    ),
                ],
                handler=SSMConfiguration,
            ),
        ],
        data_types=[
            plugins.DataType(name='string', label='String'),
            plugins.DataType(name='string_list', label='String List'),
            plugins.DataType(name='secret', label='Secret', secret=True),
        ],
        vertex_labels=[
            plugins.PluginVertexLabel(
                name='AwsAccount',
                model_ref='imbi_plugin_aws.models:AwsAccount',
                indexes=[
                    plugins.PluginIndex(fields=['account_id'], unique=True),
                    plugins.PluginIndex(fields=['name']),
                ],
            ),
        ],
        edge_labels=[
            plugins.PluginEdgeLabel(
                name='MAPS_TO',
                from_labels=['Environment'],
                to_labels=['AwsAccount'],
                properties={'tags': 'dict[str, str]'},
            ),
        ],
        # The API writes ``{action, plugin_slug, key, data_type, secret}``
        # to operations_log.description for every set/delete in
        # ``project_configuration._write_audit``.
        ops_log_templates={
            'set_value': plugins.OpsLogTemplate(
                label='Set parameter "{{key}}"',
                summary='set parameter',
            ),
            'delete_key': plugins.OpsLogTemplate(
                label='Deleted parameter "{{key}}"',
                summary='deleted parameter',
            ),
        },
    )


__all__ = ['AWSPlugin']
