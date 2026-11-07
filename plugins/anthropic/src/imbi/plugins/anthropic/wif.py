"""Anthropic workload identity federation (WIF plan 3.2, 4.3, 4.5).

- :class:`AnthropicExchanger` exchanges an identity JWT for a
  ``sk-ant-oat01`` access token at a fixed endpoint (D8).
- :class:`AnthropicWif` is the ``anthropic_wif`` secret provider. A
  dynamic binding holds the exchanger target. Each resolution mints a
  new token for the agent of the task through core (``vendor_token``).

The assertion and the token are never logged. Every refused exchange
is the same opaque ``401`` from Anthropic.
"""

import typing

import pydantic

from imbi.common.plugins import identity

#: Fixed in code (D8). No tenant setting can change it.
TOKEN_URL = 'https://api.anthropic.com/v1/oauth/token'
_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:jwt-bearer'
#: A jwt-bearer exchange needs both betas: ``oauth-2025-04-20`` opens
#: the token endpoint, and ``oidc-federation-2026-04-01`` sends the
#: request to the federation handler (anthropic SDK
#: ``lib/credentials/_workload.py``).
_BETA = 'oauth-2025-04-20,oidc-federation-2026-04-01'

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
        # Anthropic gives no reason for a refusal; see the Console
        # authentication history.
        return await identity.post_exchange(
            'Anthropic',
            TOKEN_URL,
            {
                'grant_type': _GRANT_TYPE,
                'assertion': identity_token,
                **target,
            },
            {'anthropic-beta': _BETA},
        )


EXCHANGER = AnthropicExchanger()


class AnthropicWif(identity.WifSecretProvider):
    """``anthropic_wif``: a model token for the agent of the task."""

    type = 'anthropic_wif'
    label = 'Anthropic workload identity'
    exchanger = EXCHANGER
