"""The workload identity contracts (WIF plan sections 4.1 and 4.3).

Two contracts:

- An :class:`IdentitySource` gets a signed identity JWT for Imbi (for
  example, from AWS STS ``GetWebIdentityToken``). A plugin declares its
  sources in :attr:`PluginManifest.identity_sources
  <imbi.common.plugins.base.PluginManifest.identity_sources>`. An
  organization selects one source in its ``workload_identity`` setting.
- A :class:`TokenExchanger` exchanges that JWT for a short-lived access
  token of a model vendor. The vendor plugin uses its exchanger
  directly for its secret provider, and declares it in
  :attr:`PluginManifest.token_exchangers
  <imbi.common.plugins.base.PluginManifest.token_exchangers>` for the
  AI Providers of that vendor.

Core supplies every claim value in an :class:`IdentityRequest`. A
source never takes a claim value from its configuration. Plugins are
still trusted code: this does not isolate a malicious plugin.

The identity JWT and the access token are never logged, traced, or
written to an audit row. :class:`AccessToken` has no readable ``repr``
and cannot be pickled. Audit rows use :attr:`AccessToken.fingerprint`.
"""

import dataclasses
import datetime
import hashlib
import json
import logging
import typing

import httpx
import pydantic

from imbi.common.plugins import secrets
from imbi.common.plugins.secrets import InvalidConfiguration, validate_model

__all__ = [
    'AccessToken',
    'IdentityError',
    'IdentityRequest',
    'IdentitySource',
    'InvalidConfiguration',
    'TokenExchanger',
    'WifSecretProvider',
    'post_exchange',
    'target_keys',
    'validate_model',
]

LOGGER = logging.getLogger(__name__)

#: The timeout of one exchange request.
EXCHANGE_TIMEOUT_SECONDS = 10


class IdentityError(Exception):
    """A failure to get an identity JWT or an access token.

    ``reason`` is a safe reason code. It never holds vendor text, the
    JWT, or the token. ``retryable`` is true only when a new attempt,
    with a new JWT, can succeed.
    """

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclasses.dataclass(frozen=True)
class IdentityRequest:
    """The claims of one identity JWT. Core sets every value."""

    #: The Imbi organization id.
    organization_id: str
    #: The ``aud`` claim. It comes from the exchanger, fixed in code.
    audience: str
    #: ``imbi_org`` and ``imbi_agent`` (or ``imbi_ai_provider``).
    #: Immutable ids only.
    tags: dict[str, str]
    #: The JWT lifetime. It comes from the exchanger.
    duration_seconds: int
    signing_algorithm: str = 'RS256'


class AccessToken:
    """A vendor access token. No readable ``repr``, no pickling."""

    __slots__ = ('expires_at', 'scope', 'token')

    def __init__(
        self,
        token: str,
        expires_at: datetime.datetime,
        scope: str | None = None,
    ) -> None:
        self.token = token
        self.expires_at = expires_at
        self.scope = scope

    @property
    def fingerprint(self) -> str:
        """The first 12 hex digits of the SHA-256 of the token."""
        return hashlib.sha256(self.token.encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        return '<AccessToken redacted>'

    __str__ = __repr__

    def __reduce__(self) -> typing.NoReturn:
        raise TypeError('AccessToken cannot be serialized')


class IdentitySource:
    """The identity source contract.

    Subclasses set :attr:`type` and :attr:`label`. imbi-api creates one
    instance of each type.
    """

    type: typing.ClassVar[str]
    label: typing.ClassVar[str]

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Return the normalized configuration. No external call.

        Raises:
            InvalidConfiguration: The configuration is not valid.

        """
        raise NotImplementedError

    async def check_config(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> None:
        """Check a validated configuration against the external system.

        Called when the setting is written. It does not get a JWT.

        Raises:
            InvalidConfiguration: The configuration is not safe to use.

        """

    async def identity_token(
        self, config: dict[str, typing.Any], request: IdentityRequest
    ) -> str:
        """Return a new signed JWT for ``request``.

        Each call returns a new JWT (a new ``jti``).

        Raises:
            IdentityError: The source refused or failed.

        """
        raise NotImplementedError


class TokenExchanger:
    """The vendor token exchange contract.

    Subclasses set the class variables. The exchange endpoint is a
    constant of the subclass, and redirects are not followed.
    """

    vendor: typing.ClassVar[str]
    #: The vendor name that the UI shows.
    label: typing.ClassVar[str]
    #: The target that :meth:`validate_target` accepts, as help text for
    #: an admin: the JSON keys and where to find the values.
    target_help: typing.ClassVar[str]
    #: The model of the target, for the admin form, or ``None``.
    target_model: typing.ClassVar[type[pydantic.BaseModel] | None] = None
    #: The ``aud`` claim that the vendor accepts.
    audience: typing.ClassVar[str]
    #: The lifetime of the identity JWT (STS ``DurationSeconds``).
    jwt_seconds: typing.ClassVar[int]

    def validate_target(
        self, target: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Return the normalized target (the vendor-side ids).

        Raises:
            InvalidConfiguration: The target is not valid.

        """
        raise NotImplementedError

    async def exchange(
        self, target: dict[str, typing.Any], identity_token: str
    ) -> AccessToken:
        """Exchange ``identity_token`` once for an access token.

        Raises:
            IdentityError: The vendor refused or failed. Never retry
                with the same ``identity_token``.

        """
        raise NotImplementedError


def target_keys(model: type[pydantic.BaseModel]) -> str:
    """Return the fields of a target model as a JSON example for
    :attr:`TokenExchanger.target_help`: ``{"key": "...", ...}``."""
    return json.dumps(dict.fromkeys(model.model_fields, '...'))


async def post_exchange(
    vendor: str,
    url: str,
    body: dict[str, typing.Any],
    headers: dict[str, str] | None = None,
) -> AccessToken:
    """POST a JSON token exchange to a fixed endpoint, one time.

    Redirects are not followed. The body and the token are never logged.
    The response must hold ``access_token`` and ``expires_in``.

    Raises:
        IdentityError: ``unreachable`` and ``unavailable`` (retryable),
            ``exchange_refused``, or ``provider_error``.

    """
    try:
        async with httpx.AsyncClient(
            timeout=EXCHANGE_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as err:
        LOGGER.warning(
            '%s token exchange failed: %s', vendor, type(err).__name__
        )
        raise IdentityError('unreachable', retryable=True) from None
    if response.status_code == 429 or response.status_code >= 500:
        LOGGER.warning(
            '%s token exchange failed: HTTP %s', vendor, response.status_code
        )
        raise IdentityError('unavailable', retryable=True)
    if response.status_code != 200:
        LOGGER.warning(
            '%s token exchange refused: HTTP %s', vendor, response.status_code
        )
        raise IdentityError('exchange_refused')
    try:
        payload = response.json()
        token = payload['access_token']
        expires_in = int(payload['expires_in'])
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=expires_in
        )
    except (ValueError, KeyError, TypeError, OverflowError):
        raise IdentityError('provider_error') from None
    if not isinstance(token, str) or not token or expires_in <= 0:
        raise IdentityError('provider_error')
    return AccessToken(token, expires_at, payload.get('scope'))


class WifSecretProvider(secrets.SecretProvider):
    """A vendor WIF secret provider (``anthropic_wif``, ``openai_wif``).

    Subclasses set :attr:`type`, :attr:`label`, and :attr:`exchanger`. A
    dynamic binding holds the exchanger target. Each resolution mints a
    new token for the agent of the task through core (``vendor_token``).
    The provider takes no configuration.
    """

    exchanger: typing.ClassVar[TokenExchanger]
    capabilities = frozenset[secrets.SecretCapability]({'dynamic_issuance'})

    def locator_schema(self) -> dict[str, typing.Any] | None:
        model = self.exchanger.target_model
        return None if model is None else model.model_json_schema()

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if config:
            raise InvalidConfiguration(
                f'The {self.type} provider takes no configuration'
            )
        return {}

    def validate_locator(
        self,
        locator: dict[str, typing.Any],
        credential_class: secrets.CredentialClass,
    ) -> dict[str, typing.Any]:
        if credential_class != 'dynamic':
            raise InvalidConfiguration(f'An {self.type} binding is dynamic')
        return self.exchanger.validate_target(locator)

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: secrets.ResolveContext,
    ) -> secrets.Material:
        if field is not None:
            raise secrets.BrokerError('secret_field_not_allowed')
        if context.agent_id is None:
            raise secrets.BrokerError('secret_access_denied', 'no_agent')
        token = await self.host.vendor_token(
            context.organization_id,
            self.exchanger,
            locator,
            agent_id=context.agent_id,
        )
        return secrets.Material(
            token.token.encode(),
            bearer=True,
            credential_expires_at=token.expires_at,
        )
