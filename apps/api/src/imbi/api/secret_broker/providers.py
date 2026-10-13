"""Secret provider plugins (ADR 0022, plan sections 9.2 and 9.7).

A provider is an adapter to an external secret system. Its capabilities
are explicit data: the broker never infers them from the type. A
provider raises :class:`BrokerError` with ``operation_not_supported``
for a capability it does not have, and translates every provider error
through an allowlist into a safe reason code. It never puts a raw
provider response in an error, a log, or a return value.

Secret material is held only in :class:`Material`, which has no
readable ``repr`` and cannot be pickled.
"""

import dataclasses
import datetime
import logging
import typing
import uuid

import aioboto3  # pyright: ignore[reportMissingTypeStubs]
import orjson
import pydantic
from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    exceptions as botocore_exceptions,
)

LOGGER = logging.getLogger(__name__)

Capability = typing.Literal[
    'static_retrieval',
    'version_selection',
    'rotation_metadata',
    'dynamic_issuance',
    'lease_renewal',
    'lease_revocation',
    'health_check',
]
CredentialClass = typing.Literal['static', 'rotated', 'dynamic']

ALL_CAPABILITIES: frozenset[Capability] = frozenset(
    typing.get_args(Capability)
)

#: The error codes of the source draft, with their HTTP status.
ERROR_STATUS: dict[str, int] = {
    'invalid_secret_reference': 422,
    'secret_binding_not_found': 404,
    'secret_binding_disabled': 403,
    'secret_provider_disabled': 403,
    'secret_provider_unavailable': 503,
    'secret_access_denied': 403,
    'secret_field_not_allowed': 403,
    'delivery_mode_not_allowed': 403,
    'requested_ttl_too_large': 422,
    'resolution_not_found': 404,
    'resolution_expired': 410,
    'resolution_already_used': 409,
    'resolution_context_mismatch': 403,
    'operation_not_supported': 422,
    'provider_lease_not_renewable': 409,
    'provider_lease_not_revocable': 409,
    'provider_revocation_failed': 502,
    'secret_materialization_failed': 502,
}

_RETRYABLE = frozenset({'secret_provider_unavailable'})


class BrokerError(Exception):
    """A broker failure with a code from :data:`ERROR_STATUS`.

    ``reason`` is a safe reason code for audit events. Neither holds
    provider text or secret material.
    """

    def __init__(self, code: str, reason: str | None = None) -> None:
        if code not in ERROR_STATUS:
            raise ValueError(f'Unknown broker error code {code!r}')
        super().__init__(code)
        self.code = code
        self.reason = reason or code

    @property
    def status(self) -> int:
        return ERROR_STATUS[self.code]

    @property
    def retryable(self) -> bool:
        return self.code in _RETRYABLE


class InvalidConfiguration(ValueError):
    """Provider configuration or a binding locator is not valid.

    The message names the problem only, never a value.
    """


class Material:
    """Secret material from a provider.

    No readable ``repr``, no pickling, and no dataclass or pydantic
    serialization, so the value cannot reach a log or a stored row by
    accident.
    """

    __slots__ = (
        'binary',
        'credential_expires_at',
        'lease_id',
        'provider_version',
        'renewable',
        'revocable',
        'value',
    )

    def __init__(
        self,
        value: bytes,
        *,
        binary: bool = False,
        credential_expires_at: datetime.datetime | None = None,
        provider_version: str | None = None,
        lease_id: str | None = None,
        renewable: bool = False,
        revocable: bool = False,
    ) -> None:
        self.value = value
        self.binary = binary
        self.credential_expires_at = credential_expires_at
        self.provider_version = provider_version
        self.lease_id = lease_id
        self.renewable = renewable
        self.revocable = revocable

    def __repr__(self) -> str:
        return '<Material redacted>'

    __str__ = __repr__

    def __reduce__(self) -> typing.NoReturn:
        raise TypeError('Material cannot be serialized')


@dataclasses.dataclass(frozen=True)
class ResolveContext:
    """What a provider may know about the request. No handle."""

    organization_id: str
    task_id: uuid.UUID
    project_id: str | None
    purpose: str
    ttl_seconds: int
    credential_class: CredentialClass


@dataclasses.dataclass(frozen=True)
class Health:
    status: typing.Literal['healthy', 'unhealthy']
    reason: str | None = None
    #: Identity metadata, never credentials.
    identity: dict[str, str] = dataclasses.field(
        default_factory=dict[str, str]
    )


def select_field(value: bytes, field: str | None) -> bytes:
    """Return the value, or one string member of a JSON object.

    JSON is parsed only when a field is requested.

    Raises:
        BrokerError: The value is not a JSON object, or the member is
            missing or not a string.

    """
    if field is None:
        return value
    try:
        document = orjson.loads(value)
    except orjson.JSONDecodeError:
        raise BrokerError(
            'secret_materialization_failed', 'not_a_json_object'
        ) from None
    if not isinstance(document, dict):
        raise BrokerError('secret_materialization_failed', 'not_a_json_object')
    member = typing.cast(dict[str, typing.Any], document).get(field)
    if not isinstance(member, str):
        raise BrokerError('secret_materialization_failed', 'field_missing')
    return member.encode()


class Provider:
    """The provider plugin contract.

    Subclasses set :attr:`type` and :attr:`capabilities`, and override
    the methods of the capabilities they have.
    """

    type: typing.ClassVar[str]
    label: typing.ClassVar[str]
    capabilities: typing.ClassVar[frozenset[Capability]]

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Return the normalized configuration.

        Raises:
            InvalidConfiguration: The configuration is not valid.

        """
        raise NotImplementedError

    def validate_locator(
        self, locator: dict[str, typing.Any], credential_class: CredentialClass
    ) -> dict[str, typing.Any]:
        """Return the normalized binding locator. No provider call.

        Raises:
            InvalidConfiguration: The locator is not valid.

        """
        raise NotImplementedError

    async def health(self, config: dict[str, typing.Any]) -> Health:
        raise BrokerError('operation_not_supported')

    async def validate_binding(
        self, config: dict[str, typing.Any], locator: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Return metadata of the bound secret, never its value."""
        raise BrokerError('operation_not_supported')

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: ResolveContext,
    ) -> Material:
        raise BrokerError('operation_not_supported')

    async def renew(
        self, config: dict[str, typing.Any], lease_id: str, ttl_seconds: int
    ) -> datetime.datetime:
        raise BrokerError('provider_lease_not_renewable')

    async def revoke(
        self, config: dict[str, typing.Any], lease_id: str
    ) -> None:
        raise BrokerError('provider_lease_not_revocable')


def _validate(
    model: type[pydantic.BaseModel], value: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    try:
        return model.model_validate(value).model_dump(exclude_none=True)
    except pydantic.ValidationError as err:
        # Field paths and messages only: ``input`` would echo values.
        problems = '; '.join(
            f'{".".join(str(p) for p in e["loc"]) or "value"}: {e["msg"]}'
            for e in err.errors(include_input=False)
        )
        raise InvalidConfiguration(problems) from None


# --- fake ----------------------------------------------------------------


class _FakeLocator(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    key: str = pydantic.Field(min_length=1)


class FakeProvider(Provider):
    """A provider for tests, with every capability.

    Values live in process memory (:attr:`values`), never in the
    configuration. A ``dynamic`` binding issues a revocable lease.
    """

    type = 'fake'
    label = 'Fake (tests only)'
    capabilities = ALL_CAPABILITIES

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.leases: set[str] = set()
        self.revoked: list[str] = []
        self.fail_revoke = False
        self.unavailable = False

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if config:
            raise InvalidConfiguration(
                'The fake provider takes no configuration'
            )
        return {}

    def validate_locator(
        self, locator: dict[str, typing.Any], credential_class: CredentialClass
    ) -> dict[str, typing.Any]:
        return _validate(_FakeLocator, locator)

    async def health(self, config: dict[str, typing.Any]) -> Health:
        if self.unavailable:
            return Health('unhealthy', 'unreachable')
        return Health('healthy', identity={'provider': 'fake'})

    async def validate_binding(
        self, config: dict[str, typing.Any], locator: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return {'exists': locator['key'] in self.values}

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: ResolveContext,
    ) -> Material:
        if self.unavailable:
            raise BrokerError('secret_provider_unavailable', 'unreachable')
        value = self.values.get(locator['key'])
        if value is None:
            raise BrokerError('secret_materialization_failed', 'not_found')
        material = Material(select_field(value, field))
        if context.credential_class == 'dynamic':
            material.lease_id = f'fake-lease-{uuid.uuid4()}'
            material.revocable = True
            material.renewable = True
            material.credential_expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=context.ttl_seconds)
            self.leases.add(material.lease_id)
        return material

    async def renew(
        self, config: dict[str, typing.Any], lease_id: str, ttl_seconds: int
    ) -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=ttl_seconds
        )

    async def revoke(
        self, config: dict[str, typing.Any], lease_id: str
    ) -> None:
        if self.fail_revoke:
            raise BrokerError('provider_revocation_failed', 'unreachable')
        self.leases.discard(lease_id)
        self.revoked.append(lease_id)


# --- aws_secrets_manager -------------------------------------------------


class _AwsConfig(pydantic.BaseModel):
    """No access keys: ``extra='forbid'`` refuses them. Credentials come
    from the default chain (workload identity) or role assumption."""

    model_config = pydantic.ConfigDict(extra='forbid')

    region: str = pydantic.Field(pattern=r'^[a-z]{2}(-[a-z]+)+-[0-9]+$')
    account_id: str | None = pydantic.Field(
        default=None, pattern=r'^[0-9]{12}$'
    )
    role_arn: str | None = pydantic.Field(
        default=None,
        pattern=r'^arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$',
        max_length=2048,
    )
    endpoint_url: str | None = pydantic.Field(
        default=None, pattern=r'^https?://[^\s?#]+$'
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


def _aws_error(err: Exception) -> BrokerError:
    """Translate an AWS error. Only the error code is read."""
    if isinstance(err, botocore_exceptions.ClientError):
        code = str(
            err.response.get('Error', {}).get('Code', '')  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        )
        if code in _AWS_UNAVAILABLE:
            return BrokerError('secret_provider_unavailable', 'throttled')
        return BrokerError(
            'secret_materialization_failed',
            _AWS_REASONS.get(code, 'provider_error'),
        )
    return BrokerError('secret_provider_unavailable', 'unreachable')


class AwsSecretsManager(Provider):
    """AWS Secrets Manager: static and rotated secrets.

    Rotation is not a lease: the resolution expiry ends only Imbi
    access, and the AWS secret stays valid.
    """

    type = 'aws_secrets_manager'
    label = 'AWS Secrets Manager'
    capabilities = frozenset[Capability](
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
        return _validate(_AwsConfig, config)

    def validate_locator(
        self, locator: dict[str, typing.Any], credential_class: CredentialClass
    ) -> dict[str, typing.Any]:
        return _validate(_AwsLocator, locator)

    async def _session(self, config: dict[str, typing.Any]) -> typing.Any:
        """Return a session: the default chain, or an assumed role."""
        session: typing.Any = aioboto3.Session(region_name=config['region'])
        if not config.get('role_arn'):
            return session
        async with session.client(
            'sts', endpoint_url=config.get('endpoint_url')
        ) as sts:
            response: dict[str, typing.Any] = await sts.assume_role(
                RoleArn=config['role_arn'],
                RoleSessionName='imbi-secrets-broker',
                DurationSeconds=900,
            )
        credentials: dict[str, str] = response['Credentials']
        return aioboto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken'],
            region_name=config['region'],
        )

    async def _call(
        self,
        config: dict[str, typing.Any],
        service: str,
        method: str,
        **kwargs: typing.Any,
    ) -> dict[str, typing.Any]:
        """Call one AWS method. Errors are translated, never logged with
        the response."""
        try:
            session = await self._session(config)
            async with session.client(
                service, endpoint_url=config.get('endpoint_url')
            ) as client:
                return typing.cast(
                    dict[str, typing.Any],
                    await getattr(client, method)(**kwargs),
                )
        except BrokerError:
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

    async def health(self, config: dict[str, typing.Any]) -> Health:
        try:
            identity = await self._call(config, 'sts', 'get_caller_identity')
        except BrokerError as err:
            return Health('unhealthy', err.reason)
        account = str(identity.get('Account', ''))
        if config.get('account_id') and account != config['account_id']:
            return Health('unhealthy', 'account_mismatch')
        return Health(
            'healthy',
            identity={'account_id': account, 'arn': str(identity.get('Arn'))},
        )

    async def validate_binding(
        self, config: dict[str, typing.Any], locator: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        found = await self._call(
            config,
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
        context: ResolveContext,
    ) -> Material:
        kwargs: dict[str, str] = {'SecretId': locator['secret_id']}
        if locator.get('version_id'):
            kwargs['VersionId'] = locator['version_id']
        else:
            kwargs['VersionStage'] = locator.get('version_stage', 'AWSCURRENT')
        found = await self._call(
            config, 'secretsmanager', 'get_secret_value', **kwargs
        )
        version = found.get('VersionId')
        if found.get('SecretString') is not None:
            value = str(found['SecretString']).encode()
            return Material(
                select_field(value, field), provider_version=version
            )
        if found.get('SecretBinary') is not None:
            if field is not None:
                raise BrokerError(
                    'secret_materialization_failed', 'not_a_json_object'
                )
            return Material(
                bytes(found['SecretBinary']),
                binary=True,
                provider_version=version,
            )
        raise BrokerError('secret_materialization_failed', 'empty_secret')


#: Provider plugins, by type. One instance each.
PROVIDERS: dict[str, Provider] = {
    provider.type: provider
    for provider in (FakeProvider(), AwsSecretsManager())
}


def get(provider_type: str) -> Provider:
    """Return the provider plugin of a type.

    Raises:
        BrokerError: ``operation_not_supported`` for an unknown type.

    """
    provider = PROVIDERS.get(provider_type)
    if provider is None:
        raise BrokerError('operation_not_supported', 'unknown_provider_type')
    return provider
