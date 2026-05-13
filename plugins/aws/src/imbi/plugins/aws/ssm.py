"""AWS Systems Manager Parameter Store ConfigurationPlugin."""

from __future__ import annotations

import asyncio
import datetime
import typing

from imbi_common.plugins.base import (
    ConfigKey,
    ConfigKeyWithValue,
    ConfigurationPlugin,
    ConfigValue,
    DataType,
    OpsLogTemplate,
    PluginContext,
    PluginManifest,
    PluginOption,
)
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)
from imbi_common.plugins.templates import expand_template

from imbi_plugin_aws._helpers import (
    assignment_region,
    assignment_timeout,
    template_vars,
)
from imbi_plugin_aws.aws_session import (
    AwsCredentials,
    call_aws_json,
    resolve_credentials,
)


class _ParameterMissing(Exception):
    """Internal sentinel used to swallow ParameterNotFound on delete."""


_DATA_TYPE_TO_SSM: dict[str, str] = {
    'string': 'String',
    'string_list': 'StringList',
    'secret': 'SecureString',
}
_SSM_TO_DATA_TYPE: dict[str, str] = {
    value: key for key, value in _DATA_TYPE_TO_SSM.items()
}

# AWS SSM error codes -> imbi exceptions, used for both list/get/set/del.
_SSM_ERROR_MAP: dict[str, type[Exception]] = {
    'ExpiredTokenException': PluginCredentialsMissing,
    'UnrecognizedClientException': PluginCredentialsMissing,
    'InvalidSignatureException': PluginCredentialsMissing,
    'AccessDeniedException': PluginCredentialsMissing,
    'UnauthorizedOperation': PluginCredentialsMissing,
    'ThrottlingException': PluginUnavailableError,
    'RequestLimitExceeded': PluginUnavailableError,
    'InternalServerError': PluginUnavailableError,
    'ParameterAlreadyExists': ValueError,
    'ValidationException': ValueError,
    'ParameterNotFound': ValueError,
    'ReadTimeoutError': PluginTimeoutError,
    'ConnectTimeoutError': PluginTimeoutError,
}


def _to_datetime(value: typing.Any) -> datetime.datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value), tz=datetime.UTC)
    return None


def _strip_prefix(name: str, prefix: str) -> str:
    base = prefix.rstrip('/')
    if name.startswith(base + '/'):
        return name[len(base) + 1 :]
    return name.lstrip('/')


class SsmPlugin(ConfigurationPlugin):
    """ConfigurationPlugin backed by SSM Parameter Store."""

    manifest = PluginManifest(
        slug='aws-ssm',
        name='AWS SSM Parameter Store',
        description='Read and write project configuration as SSM parameters.',
        plugin_type='configuration',
        api_version=1,
        cacheable=False,
        options=[
            PluginOption(
                name='region',
                label='AWS Region',
                type='string',
                required=True,
                description='Region holding the project parameters.',
            ),
            PluginOption(
                name='path_prefix',
                label='Parameter Path Prefix',
                type='string',
                required=True,
                description=(
                    "Path prefix under which this project's parameters live. "
                    'Supports ${project_slug}, ${org_slug}, ${environment}, '
                    '${project_id}. Must start with /. Example: '
                    '/imbi/${environment}/${project_slug}/'
                ),
            ),
            PluginOption(
                name='kms_key_id',
                label='KMS Key ID',
                type='string',
                required=False,
                description=(
                    'KMS key id/alias for SecureString writes. Defaults to '
                    'alias/aws/ssm.'
                ),
            ),
            PluginOption(
                name='timeout_seconds',
                label='Request Timeout',
                type='integer',
                default=15,
            ),
            PluginOption(
                name='default_role_name',
                label='Default Role Name',
                type='string',
                required=False,
                description=(
                    'IAM role assumed when a per-environment account '
                    "binding doesn't specify one of its own. Falls back "
                    "to the identity plugin's default_role_name when "
                    'unset. Supports ${project_slug}, ${org_slug}, '
                    '${environment}, ${project_id}.'
                ),
            ),
        ],
        credentials=[],
        data_types=[
            DataType(name='string', label='String'),
            DataType(name='string_list', label='String List'),
            DataType(name='secret', label='Secret', secret=True),
        ],
        # The API writes ``{action, plugin_slug, key, data_type, secret}``
        # to operations_log.description for every set/delete in
        # ``project_configuration._write_audit``.
        ops_log_templates={
            'set_value': OpsLogTemplate(
                label='Set parameter "{{key}}"',
                summary='set parameter',
            ),
            'delete_key': OpsLogTemplate(
                label='Deleted parameter "{{key}}"',
                summary='deleted parameter',
            ),
        },
    )

    async def list_keys(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[ConfigKey]:
        prefix = self._prefix(ctx)
        creds = resolve_credentials(
            credentials, region=assignment_region(ctx), ctx=ctx
        )
        timeout = assignment_timeout(ctx, default=15.0)
        keys: list[ConfigKey] = []
        next_token: str | None = None
        while True:
            body: dict[str, typing.Any] = {
                'ParameterFilters': [
                    {
                        'Key': 'Path',
                        'Option': 'Recursive',
                        'Values': [prefix],
                    }
                ],
                'MaxResults': 50,
            }
            if next_token:
                body['NextToken'] = next_token
            response = await call_aws_json(
                service='ssm',
                action='DescribeParameters',
                body=body,
                credentials=creds,
                error_map=_SSM_ERROR_MAP,
                timeout=timeout,
            )
            for param in response.get('Parameters', []):
                keys.append(
                    ConfigKey(
                        key=_strip_prefix(str(param['Name']), prefix),
                        data_type=_SSM_TO_DATA_TYPE.get(
                            str(param.get('Type', '')), 'string'
                        ),
                        last_modified=_to_datetime(
                            param.get('LastModifiedDate')
                        ),
                        secret=str(param.get('Type')) == 'SecureString',
                    )
                )
            next_token = response.get('NextToken')
            if not next_token:
                break
        return keys

    async def get_values(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        keys: list[str] | None = None,
    ) -> list[ConfigKeyWithValue]:
        prefix = self._prefix(ctx)
        creds = resolve_credentials(
            credentials, region=assignment_region(ctx), ctx=ctx
        )
        timeout = assignment_timeout(ctx, default=15.0)
        if keys is None:
            return await self._get_all_values(creds, prefix, timeout)
        return await self._get_specific_values(creds, prefix, keys, timeout)

    async def _get_all_values(
        self,
        creds: AwsCredentials,
        prefix: str,
        timeout: float,
    ) -> list[ConfigKeyWithValue]:
        results: list[ConfigKeyWithValue] = []
        next_token: str | None = None
        while True:
            body: dict[str, typing.Any] = {
                'Path': prefix,
                'Recursive': True,
                'WithDecryption': True,
                'MaxResults': 10,
            }
            if next_token:
                body['NextToken'] = next_token
            response = await call_aws_json(
                service='ssm',
                action='GetParametersByPath',
                body=body,
                credentials=creds,
                error_map=_SSM_ERROR_MAP,
                timeout=timeout,
            )
            for param in response.get('Parameters', []):
                results.append(_param_to_kv(param, prefix))
            next_token = response.get('NextToken')
            if not next_token:
                break
        return results

    async def _get_specific_values(
        self,
        creds: AwsCredentials,
        prefix: str,
        keys: list[str],
        timeout: float,
    ) -> list[ConfigKeyWithValue]:
        names = [_full_name(prefix, key) for key in keys]
        batches = [names[i : i + 10] for i in range(0, len(names), 10)]

        async def fetch_batch(
            batch: list[str],
        ) -> list[ConfigKeyWithValue]:
            try:
                response = await call_aws_json(
                    service='ssm',
                    action='GetParameters',
                    body={'Names': batch, 'WithDecryption': True},
                    credentials=creds,
                    error_map=_SSM_ERROR_MAP,
                    timeout=timeout,
                )
            except ValueError:
                # Per the contract, missing names are omitted.
                return []
            return [
                _param_to_kv(param, prefix)
                for param in response.get('Parameters', [])
            ]

        per_batch = await asyncio.gather(*(fetch_batch(b) for b in batches))
        return [kv for batch_results in per_batch for kv in batch_results]

    async def set_value(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
        value: ConfigValue,
    ) -> ConfigKey:
        prefix = self._prefix(ctx)
        if '..' in key or key.startswith('/'):
            raise ValueError(
                f'Invalid SSM key {key!r}: keys must be relative '
                "to the assignment's path_prefix"
            )
        creds = resolve_credentials(
            credentials, region=assignment_region(ctx), ctx=ctx
        )
        timeout = assignment_timeout(ctx, default=15.0)
        ssm_type = _DATA_TYPE_TO_SSM.get(value.data_type)
        if ssm_type is None:
            raise ValueError(
                f'Unknown data_type {value.data_type!r}; expected '
                f'one of {sorted(_DATA_TYPE_TO_SSM)}'
            )
        full_name = _full_name(prefix, key)
        put_body: dict[str, typing.Any] = {
            'Name': full_name,
            'Value': value.value,
            'Type': ssm_type,
            'Overwrite': True,
            'Tier': 'Standard',
        }
        if value.data_type == 'secret':
            kms_key_id = ctx.assignment_options.get('kms_key_id')
            if kms_key_id:
                put_body['KeyId'] = str(kms_key_id)
        await call_aws_json(
            service='ssm',
            action='PutParameter',
            body=put_body,
            credentials=creds,
            error_map=_SSM_ERROR_MAP,
            timeout=timeout,
        )
        # Read back so we return authoritative LastModifiedDate.
        get_resp = await call_aws_json(
            service='ssm',
            action='GetParameter',
            body={'Name': full_name, 'WithDecryption': False},
            credentials=creds,
            error_map=_SSM_ERROR_MAP,
            timeout=timeout,
        )
        param = typing.cast(
            dict[str, typing.Any], get_resp.get('Parameter', {})
        )
        return ConfigKey(
            key=key,
            data_type=value.data_type,
            last_modified=_to_datetime(param.get('LastModifiedDate')),
            secret=value.data_type == 'secret',
        )

    async def delete_key(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
    ) -> None:
        prefix = self._prefix(ctx)
        creds = resolve_credentials(
            credentials, region=assignment_region(ctx), ctx=ctx
        )
        timeout = assignment_timeout(ctx, default=15.0)
        full_name = _full_name(prefix, key)
        # Deletion is idempotent: route ParameterNotFound through a
        # private sentinel so we can swallow it without dropping other
        # ValidationException paths the operator does want to see.
        error_map = {
            **_SSM_ERROR_MAP,
            'ParameterNotFound': _ParameterMissing,
        }
        try:
            await call_aws_json(
                service='ssm',
                action='DeleteParameter',
                body={'Name': full_name},
                credentials=creds,
                error_map=error_map,
                timeout=timeout,
            )
        except _ParameterMissing:
            return

    @staticmethod
    def _prefix(ctx: PluginContext) -> str:
        raw = ctx.assignment_options.get('path_prefix')
        if not isinstance(raw, str) or not raw:
            raise ValueError('aws-ssm requires the "path_prefix" option')
        expanded = expand_template(raw, template_vars(ctx))
        if not expanded.startswith('/') or expanded == '/':
            raise ValueError(
                f'Invalid path_prefix {expanded!r}: must start with /'
                ' and not be the root.'
            )
        return expanded


def _full_name(prefix: str, key: str) -> str:
    return f'{prefix.rstrip("/")}/{key.lstrip("/")}'


def _param_to_kv(
    param: dict[str, typing.Any], prefix: str
) -> ConfigKeyWithValue:
    ssm_type = str(param.get('Type', ''))
    return ConfigKeyWithValue(
        key=_strip_prefix(str(param['Name']), prefix),
        data_type=_SSM_TO_DATA_TYPE.get(ssm_type, 'string'),
        last_modified=_to_datetime(param.get('LastModifiedDate')),
        secret=ssm_type == 'SecureString',
        value=str(param.get('Value', '')),
    )


__all__ = ['SsmPlugin']
