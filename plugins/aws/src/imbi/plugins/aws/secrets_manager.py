"""The ``aws_secrets_manager`` secret provider (ADR 0022, plan 9.7).

imbi-api's secrets broker reads static and rotated secrets from the
organization's AWS account. It assumes the organization's role with
``sts:ExternalId`` ``imbi:<organization id>`` (:func:`external_id`), and
never reads with its own AWS identity.
"""

import logging
import os
import secrets as stdlib_secrets
import typing
import uuid

import aioboto3  # pyright: ignore[reportMissingTypeStubs]
import pydantic
from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    exceptions as botocore_exceptions,
)

from imbi.common.plugins import secrets

LOGGER = logging.getLogger(__name__)


class RoleConfig(pydantic.BaseModel):
    """No access keys and no endpoint: ``extra='forbid'`` refuses them.

    ``role_arn`` is required. imbi-api always assumes the tenant's role,
    so an organization can never read with Imbi's own AWS identity.
    """

    model_config = pydantic.ConfigDict(extra='forbid')

    region: str = pydantic.Field(pattern=r'^[a-z]{2}(-[a-z]+)+-[0-9]+$')
    account_id: str | None = pydantic.Field(
        default=None, pattern=r'^[0-9]{12}$'
    )
    role_arn: str = pydantic.Field(
        pattern=r'^arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$',
        max_length=2048,
    )


class _AwsLocator(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    secret_id: str = pydantic.Field(min_length=1, max_length=2048)
    version_stage: str | None = pydantic.Field(
        default=None, min_length=1, max_length=256
    )
    version_id: str | None = pydantic.Field(
        default=None, min_length=32, max_length=64
    )

    @pydantic.model_validator(mode='after')
    def _one_version(self) -> typing.Self:
        if self.version_stage and self.version_id:
            raise ValueError(
                'version_stage and version_id are mutually exclusive'
            )
        return self


#: AWS error codes, by safe reason code. Anything else is
#: ``provider_error``.
_AWS_REASONS = {
    'ResourceNotFoundException': 'not_found',
    'AccessDeniedException': 'access_denied',
    'AccessDenied': 'access_denied',
    'DecryptionFailure': 'decryption_failed',
    'InvalidRequestException': 'invalid_request',
    'InvalidParameterException': 'invalid_request',
    'ExpiredTokenException': 'credentials_expired',
}
_AWS_UNAVAILABLE = frozenset(
    {'ThrottlingException', 'InternalServiceError', 'ServiceUnavailable'}
)


def _aws_error(err: Exception) -> secrets.BrokerError:
    """Translate an AWS error. Only the error code is read."""
    if isinstance(err, botocore_exceptions.ClientError):
        code = str(
            err.response.get('Error', {}).get('Code', '')  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        )
        if code in _AWS_UNAVAILABLE:
            return secrets.BrokerError(
                'secret_provider_unavailable', 'throttled'
            )
        return secrets.BrokerError(
            'secret_materialization_failed',
            _AWS_REASONS.get(code, 'provider_error'),
        )
    return secrets.BrokerError('secret_provider_unavailable', 'unreachable')


def external_id(organization_id: str) -> str:
    """The ``sts:ExternalId`` of an organization's role assumption.

    An operator puts this value in the trust policy of the role, as the
    condition ``"StringEquals": {"sts:ExternalId": "imbi:<org id>"}``,
    so no other organization can assume that role through Imbi.
    """
    return f'imbi:{organization_id}'


def _assume_role_args(
    config: dict[str, typing.Any], external: str, **overrides: typing.Any
) -> dict[str, typing.Any]:
    """The AssumeRole arguments. The probe and the real call share them,
    so only the ExternalId can make the probe fail."""
    return {
        'RoleArn': config['role_arn'],
        'RoleSessionName': 'imbi-secrets-broker',
        'ExternalId': external,
        'DurationSeconds': 900,
    } | overrides


def _endpoint_url() -> str | None:
    """An operator override for AWS endpoints, for LocalStack in tests
    and development. Never from tenant configuration."""
    return os.environ.get('IMBI_SECRETS_AWS_ENDPOINT_URL') or None


async def assume_role(
    config: dict[str, typing.Any],
    organization_id: str,
    **overrides: typing.Any,
) -> dict[str, typing.Any]:
    """Assume the organization's role; return the ``Credentials``.

    imbi-api's own identity (workload identity or the default chain)
    only calls ``sts:AssumeRole``. The ``ExternalId`` is
    :func:`external_id` of the organization, so the trust policy of a
    role can name the one organization that may use it. ``overrides``
    replace AssumeRole arguments (``RoleSessionName``,
    ``DurationSeconds``).
    """
    session: typing.Any = aioboto3.Session(region_name=config['region'])
    async with session.client('sts', endpoint_url=_endpoint_url()) as sts:
        response: dict[str, typing.Any] = await sts.assume_role(
            **_assume_role_args(
                config, external_id(organization_id), **overrides
            )
        )
    return typing.cast(dict[str, typing.Any], response['Credentials'])


async def _external_id_problem(config: dict[str, typing.Any]) -> str | None:
    """Return ``None`` when the role refuses a wrong ExternalId.

    The probe assumes the role with a random ExternalId that no trust
    policy names. If AWS allows it, the trust policy does not require
    the ExternalId, and any organization could use the role.
    """
    probe = f'imbi:probe-{stdlib_secrets.token_hex(8)}'
    try:
        session: typing.Any = aioboto3.Session(region_name=config['region'])
        async with session.client('sts', endpoint_url=_endpoint_url()) as sts:
            await sts.assume_role(**_assume_role_args(config, probe))
    except botocore_exceptions.ClientError as err:
        code = str(
            err.response.get('Error', {}).get('Code', '')  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        )
        if code in ('AccessDenied', 'AccessDeniedException'):
            return None
        return 'role_not_verified'
    except Exception as err:  # noqa: BLE001 - fail closed
        LOGGER.warning('AWS role probe failed: %s', type(err).__name__)
        return 'role_not_verified'
    return 'role_does_not_require_external_id'


async def check_role(
    config: dict[str, typing.Any], organization_id: str
) -> None:
    """Refuse a role that the organization does not control.

    Two calls: the role must refuse a wrong ExternalId, and it must
    accept the organization's own ExternalId. The second call stops an
    organization from claiming a role that only another organization
    can assume.

    Raises:
        secrets.InvalidConfiguration: ``role_does_not_require_external_id``
            or ``role_not_verified``.

    """
    problem = await _external_id_problem(config)
    if problem is None:
        try:
            await assume_role(config, organization_id)
        except Exception as err:  # noqa: BLE001 - fail closed
            LOGGER.warning(
                'AWS role ownership check failed: %s', type(err).__name__
            )
            problem = 'role_not_verified'
    if problem is not None:
        raise secrets.InvalidConfiguration(
            'The role trust policy must require sts:ExternalId '
            f'"{external_id(organization_id)}"'
            if problem == 'role_does_not_require_external_id'
            else 'The role cannot be assumed with sts:ExternalId '
            f'"{external_id(organization_id)}"',
            code=problem,
        )


class AwsSecretsManager(secrets.SecretProvider):
    """AWS Secrets Manager: static and rotated secrets.

    Rotation is not a lease: the resolution expiry ends only Imbi
    access, and the AWS secret stays valid.
    """

    type = 'aws_secrets_manager'
    label = 'AWS Secrets Manager'
    capabilities = frozenset[secrets.SecretCapability](
        {
            'static_retrieval',
            'version_selection',
            'rotation_metadata',
            'health_check',
        }
    )

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return secrets.validate_model(RoleConfig, config)

    def validate_locator(
        self,
        locator: dict[str, typing.Any],
        credential_class: secrets.CredentialClass,
    ) -> dict[str, typing.Any]:
        return secrets.validate_model(_AwsLocator, locator)

    async def _session(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> typing.Any:
        """Return a session for the organization's role."""
        credentials = await assume_role(config, organization_id)
        return aioboto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken'],
            region_name=config['region'],
        )

    async def check_config(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> None:
        await check_role(config, organization_id)

    async def _call(
        self,
        config: dict[str, typing.Any],
        organization_id: str,
        service: str,
        method: str,
        **kwargs: typing.Any,
    ) -> dict[str, typing.Any]:
        """Call one AWS method. Errors are translated, never logged with
        the response."""
        try:
            session = await self._session(config, organization_id)
            async with session.client(
                service, endpoint_url=_endpoint_url()
            ) as client:
                return typing.cast(
                    dict[str, typing.Any],
                    await getattr(client, method)(**kwargs),
                )
        except secrets.BrokerError:
            raise
        except Exception as err:  # noqa: BLE001 - translated below
            error = _aws_error(err)
            LOGGER.warning(
                'AWS %s.%s failed: %s (%s)',
                service,
                method,
                error.reason,
                type(err).__name__,
            )
            raise error from None

    async def health(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> secrets.Health:
        problem = await _external_id_problem(config)
        if problem is not None:
            return secrets.Health('unhealthy', problem)
        try:
            identity = await self._call(
                config, organization_id, 'sts', 'get_caller_identity'
            )
        except secrets.BrokerError as err:
            return secrets.Health('unhealthy', err.reason)
        account = str(identity.get('Account', ''))
        if config.get('account_id') and account != config['account_id']:
            return secrets.Health('unhealthy', 'account_mismatch')
        return secrets.Health(
            'healthy',
            identity={'account_id': account, 'arn': str(identity.get('Arn'))},
        )

    async def validate_binding(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
        binding_id: uuid.UUID | None = None,
    ) -> dict[str, typing.Any]:
        found = await self._call(
            config,
            organization_id,
            'secretsmanager',
            'describe_secret',
            SecretId=locator['secret_id'],
        )
        stages = {
            stage
            for values in found.get('VersionIdsToStages', {}).values()
            for stage in values
        }
        return {
            'name': found.get('Name'),
            'rotation_enabled': bool(found.get('RotationEnabled')),
            'last_rotated_at': found.get('LastRotatedDate'),
            'last_changed_at': found.get('LastChangedDate'),
            'version_stage_present': (
                locator.get('version_stage', 'AWSCURRENT') in stages
                if not locator.get('version_id')
                else None
            ),
        }

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: secrets.ResolveContext,
    ) -> secrets.Material:
        kwargs: dict[str, str] = {'SecretId': locator['secret_id']}
        if locator.get('version_id'):
            kwargs['VersionId'] = locator['version_id']
        else:
            kwargs['VersionStage'] = locator.get('version_stage', 'AWSCURRENT')
        found = await self._call(
            config,
            context.organization_id,
            'secretsmanager',
            'get_secret_value',
            **kwargs,
        )
        version = found.get('VersionId')
        if found.get('SecretString') is not None:
            value = str(found['SecretString']).encode()
            return secrets.Material(
                secrets.select_field(value, field), provider_version=version
            )
        if found.get('SecretBinary') is not None:
            if field is not None:
                raise secrets.BrokerError(
                    'secret_materialization_failed', 'not_a_json_object'
                )
            return secrets.Material(
                bytes(found['SecretBinary']),
                binary=True,
                provider_version=version,
            )
        raise secrets.BrokerError(
            'secret_materialization_failed', 'empty_secret'
        )
