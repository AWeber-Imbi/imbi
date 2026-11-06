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
import typing

from imbi.common.plugins.secrets import InvalidConfiguration, validate_model

__all__ = [
    'AccessToken',
    'IdentityError',
    'IdentityRequest',
    'IdentitySource',
    'InvalidConfiguration',
    'TokenExchanger',
    'validate_model',
]


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
