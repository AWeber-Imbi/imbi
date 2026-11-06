"""Anthropic workload identity federation (WIF plan 3.2, 4.3, 4.5).

- :class:`AnthropicExchanger` exchanges an identity JWT for a
  ``sk-ant-oat01`` access token at a fixed endpoint (D8).
- :class:`AnthropicWif` is the ``anthropic_wif`` secret provider. A
  dynamic binding holds the exchanger target. Each resolution mints a
  new token for the agent of the task through core (``vendor_token``).

The assertion and the token are never logged. Every refused exchange
is the same opaque ``401`` from Anthropic.
"""

import datetime
import logging
import typing

import httpx
import pydantic

from imbi.common.plugins import identity, secrets

LOGGER = logging.getLogger(__name__)

#: Fixed in code (D8). No tenant setting can change it.
TOKEN_URL = 'https://api.anthropic.com/v1/oauth/token'
_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:jwt-bearer'
_TIMEOUT_SECONDS = 10

_Id = typing.Annotated[
    str,
    pydantic.StringConstraints(
        min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$'
    ),
]


class _Target(pydantic.BaseModel):
    """The Anthropic ids of one agent's service account and rule."""

    model_config = pydantic.ConfigDict(extra='forbid')

    organization_id: _Id
    federation_rule_id: _Id
    service_account_id: _Id
    #: Required when the rule names more than one workspace.
    workspace_id: _Id | None = None


class AnthropicExchanger(identity.TokenExchanger):
    vendor = 'anthropic'
    audience = 'https://api.anthropic.com'
    #: The JWT is used once, for the exchange. The rule sets the
    #: lifetime of the access token.
    jwt_seconds = 300

    def validate_target(
        self, target: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return identity.validate_model(_Target, target)

    async def exchange(
        self, target: dict[str, typing.Any], identity_token: str
    ) -> identity.AccessToken:
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS, follow_redirects=False
            ) as client:
                response = await client.post(
                    TOKEN_URL,
                    json={
                        'grant_type': _GRANT_TYPE,
                        'assertion': identity_token,
                        **target,
                    },
                )
        except httpx.HTTPError as err:
            LOGGER.warning(
                'Anthropic token exchange failed: %s', type(err).__name__
            )
            raise identity.IdentityError(
                'unreachable', retryable=True
            ) from None
        if response.status_code == 429 or response.status_code >= 500:
            LOGGER.warning(
                'Anthropic token exchange failed: HTTP %s',
                response.status_code,
            )
            raise identity.IdentityError('unavailable', retryable=True)
        if response.status_code != 200:
            # Anthropic gives no reason; see the Console authentication
            # history.
            LOGGER.warning(
                'Anthropic token exchange refused: HTTP %s',
                response.status_code,
            )
            raise identity.IdentityError('exchange_refused')
        try:
            body = response.json()
            token = body['access_token']
            expires_in = int(body['expires_in'])
        except (ValueError, KeyError, TypeError):
            raise identity.IdentityError('provider_error') from None
        if not isinstance(token, str) or not token or expires_in <= 0:
            raise identity.IdentityError('provider_error')
        return identity.AccessToken(
            token,
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=expires_in),
            body.get('scope'),
        )


EXCHANGER = AnthropicExchanger()


class AnthropicWif(secrets.SecretProvider):
    """``anthropic_wif``: a model token for the agent of the task."""

    type = 'anthropic_wif'
    label = 'Anthropic workload identity'
    capabilities = frozenset[secrets.SecretCapability]({'dynamic_issuance'})

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if config:
            raise secrets.InvalidConfiguration(
                'The anthropic_wif provider takes no configuration'
            )
        return {}

    def validate_locator(
        self,
        locator: dict[str, typing.Any],
        credential_class: secrets.CredentialClass,
    ) -> dict[str, typing.Any]:
        if credential_class != 'dynamic':
            raise secrets.InvalidConfiguration(
                'An anthropic_wif binding is dynamic'
            )
        return EXCHANGER.validate_target(locator)

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
            EXCHANGER,
            locator,
            agent_id=context.agent_id,
        )
        return secrets.Material(
            token.token.encode(),
            bearer=True,
            credential_expires_at=token.expires_at,
        )
