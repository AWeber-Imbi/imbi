"""The secret provider contract (ADR 0022, plan sections 9.2 and 9.7).

A provider is an adapter to an external secret system. A plugin declares
its providers in :attr:`PluginManifest.secret_providers
<imbi.common.plugins.base.PluginManifest.secret_providers>`, and
imbi-api's secrets broker creates one instance of each, with a
:class:`SecretProviderHost` for the broker services it needs. Its
capabilities are explicit data: the broker never infers them from the
type. A
provider raises :class:`BrokerError` with ``operation_not_supported``
for a capability it does not have, and translates every provider error
through an allowlist into a safe reason code. It never puts a raw
provider response in an error, a log, or a return value.

Secret material is held only in :class:`Material`, which has no
readable ``repr`` and cannot be pickled.
"""

import dataclasses
import datetime
import re
import typing
import uuid

import orjson
import pydantic

if typing.TYPE_CHECKING:
    from imbi.common import graph
    from imbi.common.plugins import identity

SecretCapability = typing.Literal[
    'static_retrieval',
    'version_selection',
    'rotation_metadata',
    'dynamic_issuance',
    'lease_renewal',
    'lease_revocation',
    'health_check',
]
CredentialClass = typing.Literal['static', 'rotated', 'dynamic']

ALL_CAPABILITIES: frozenset[SecretCapability] = frozenset(
    typing.get_args(SecretCapability)
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

    The message names the problem only, never a value. ``code`` is the
    error code that the API returns.
    """

    def __init__(
        self, message: str, code: str = 'invalid_configuration'
    ) -> None:
        super().__init__(message)
        self.code = code


class Material:
    """Secret material from a provider.

    No readable ``repr``, no pickling, and no dataclass or pydantic
    serialization, so the value cannot reach a log or a stored row by
    accident.
    """

    __slots__ = (
        'bearer',
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
        bearer: bool = False,
        credential_expires_at: datetime.datetime | None = None,
        provider_version: str | None = None,
        lease_id: str | None = None,
        renewable: bool = False,
        revocable: bool = False,
    ) -> None:
        self.value = value
        self.binary = binary
        #: An OAuth access token: the client sends it in
        #: ``Authorization: Bearer``, not as an API key.
        self.bearer = bearer
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
    #: The binding that asks. A provider that reads its own key from
    #: another binding names this one as the consumer.
    binding_id: uuid.UUID | None = None
    #: The ``owner/name`` repository that the runner asks a token for.
    repository: str | None = None
    #: The agent of the task. The broker takes it from the resolution
    #: (the task record), never from the request.
    agent_id: str | None = None


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


_REFERENCE = re.compile(
    r'secret://(?P<scope>[a-z0-9_]+)/(?P<path>[a-z0-9_]+(?:/[a-z0-9_]+)*)'
    r'(?:#(?P<field>[A-Za-z0-9_-]+))?'
)
_MAX_REFERENCE_LENGTH = 512


@dataclasses.dataclass(frozen=True)
class Reference:
    """A parsed ``secret://<scope>/<path>[#<field>]``."""

    scope: str
    path: str
    field: str | None

    @property
    def binding(self) -> str:
        """The reference without the field: what a binding stores."""
        return f'secret://{self.scope}/{self.path}'

    def __str__(self) -> str:
        return self.binding + (f'#{self.field}' if self.field else '')


def parse_reference(value: str, *, field: bool = True) -> Reference:
    """Parse a reference. Only the canonical form is accepted.

    Scope and path segments are lower case letters, digits, and
    underscores. Matching is case sensitive. There is no other
    spelling of a reference, so the input is its canonical form.

    Raises:
        BrokerError: ``invalid_secret_reference``.

    """
    match = (
        _REFERENCE.fullmatch(value)
        if len(value) <= _MAX_REFERENCE_LENGTH
        else None
    )
    if match is None or (not field and match['field']):
        raise BrokerError('invalid_secret_reference')
    return Reference(match['scope'], match['path'], match['field'])


class SecretProviderHost(typing.Protocol):
    """The broker services that imbi-api gives each provider."""

    def graph(self) -> graph.Graph:
        """Return the graph of imbi-api.

        Raises:
            BrokerError: ``secret_provider_unavailable`` when the graph
                is not open.

        """
        ...

    async def provider_key(
        self,
        organization_id: str,
        reference: str,
        *,
        consumer: uuid.UUID | None,
        host: str,
        app_id: str,
        task_id: uuid.UUID | None = None,
    ) -> Material:
        """Return the material of a provider key for one consumer.

        A provider key is a binding that only imbi-api reads, for
        example the private key of a GitHub App. Its
        ``provider_key_usage`` names the ``host``, the ``app_id``, and
        the consumer bindings that may use it. No grant gives it to a
        task.

        Raises:
            BrokerError: The binding is not a provider key for this
                consumer, host, and App id, or its provider failed.

        """
        ...

    async def check_provider_key(
        self,
        organization_id: str,
        reference: str,
        *,
        host: str,
        app_id: str,
    ) -> object:
        """Check that a binding is a provider key for ``host`` and
        ``app_id``, without reading it.

        Raises:
            BrokerError: The binding is not such a provider key.

        """
        ...

    async def vendor_token(
        self,
        organization_id: str,
        exchanger: identity.TokenExchanger,
        target: dict[str, typing.Any],
        *,
        agent_id: str,
    ) -> identity.AccessToken:
        """Mint a vendor access token for an agent (WIF plan 4.4).

        Core gets a new identity JWT from the organization's identity
        source and sets every claim. ``target`` must come from the
        binding of the agent, never from a request.

        Raises:
            BrokerError: Core or the vendor refused:
                ``secret_provider_unavailable`` when a retry can work,
                else ``secret_materialization_failed``. The reason is
                the :class:`identity.IdentityError` reason.

        """
        ...


class NoConfig(pydantic.BaseModel):
    """The configuration of a provider that takes none: ``{}``."""

    model_config = pydantic.ConfigDict(extra='forbid')


#: A model class. ``type`` is a class variable in a provider body.
_Model = type[pydantic.BaseModel]


def json_schema(model: _Model | None) -> dict[str, typing.Any] | None:
    """Return the JSON Schema of ``model``, or ``None`` without one."""
    return None if model is None else model.model_json_schema()


class SecretProvider:
    """The provider contract.

    Subclasses set :attr:`type`, :attr:`label`, and :attr:`capabilities`,
    and override the methods of the capabilities they have. The broker
    creates one instance for each type, with its :class:`SecretProviderHost`.
    """

    type: typing.ClassVar[str]
    label: typing.ClassVar[str]
    capabilities: typing.ClassVar[frozenset[SecretCapability]]
    #: The model of a binding locator, for the admin form. A provider
    #: without one gets a JSON editor. :meth:`validate_locator` still
    #: makes the decision, for example on fields that depend on each
    #: other.
    locator_model: typing.ClassVar[_Model | None] = None
    #: The model of the provider configuration, for the admin form. A
    #: provider without one gets a JSON editor, or no fields when it
    #: takes no configuration.
    config_model: typing.ClassVar[_Model | None] = None

    def __init__(self, host: SecretProviderHost) -> None:
        self.host = host

    def config_schema(self) -> dict[str, typing.Any] | None:
        """Return the JSON Schema of the configuration, or ``None``."""
        return json_schema(self.config_model)

    def locator_schema(self) -> dict[str, typing.Any] | None:
        """Return the JSON Schema of a locator, or ``None``."""
        return json_schema(self.locator_model)

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

    async def check_config(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> None:
        """Check a validated configuration against the provider.

        Called when a provider is created and when its configuration
        changes.

        Raises:
            InvalidConfiguration: The configuration is not safe to use.

        """

    async def check_locator(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
    ) -> None:
        """Check a validated locator against other bindings.

        Called when a binding is written, and for each binding of a
        provider when its configuration changes.

        Raises:
            InvalidConfiguration: The locator is not safe to use.

        """

    async def health(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> Health:
        raise BrokerError('operation_not_supported')

    async def validate_binding(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
        binding_id: uuid.UUID | None = None,
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

    def check_key_host(self, host: str) -> str:
        """Return the normalized ``host`` of a provider key that this
        provider reads (``provider_key_usage.host``).

        Raises:
            ValueError: The host is not allowed, or the provider reads
                no provider keys (the default).

        """
        del host
        raise ValueError(f'The {self.type} provider reads no provider keys')

    def repository(
        self, config: dict[str, typing.Any], url: str
    ) -> tuple[str, str] | None:
        """Return ``(host, owner/name)`` of the repository at ``url``.

        For a provider that issues repository tokens: the agent runner
        clones the repository and asks the provider for a token on
        that host. ``None``: ``url`` is not a repository on the host of
        this configuration (the default).
        """
        del config, url
        return None


def validate_model(
    model: type[pydantic.BaseModel], value: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Return ``value`` validated by ``model``, without ``None`` fields.

    Raises:
        InvalidConfiguration: With field paths and messages only, never
            the input values.

    """
    try:
        return model.model_validate(value).model_dump(exclude_none=True)
    except pydantic.ValidationError as err:
        # Field paths and messages only: ``input`` would echo values.
        problems = '; '.join(
            f'{".".join(str(p) for p in e["loc"]) or "value"}: {e["msg"]}'
            for e in err.errors(include_input=False)
        )
        raise InvalidConfiguration(problems) from None
