"""OpenAI workload identity federation (WIF plan 3.3, 4.3, 4.5).

- :class:`OpenAIExchanger` exchanges an identity JWT for an OpenAI
  access token at a fixed endpoint (D8), with an RFC 8693 token
  exchange.
- :class:`OpenAIWif` is the ``openai_wif`` secret provider. A dynamic
  binding holds the exchanger target. Each resolution mints a new token
  for the agent of the task through core (``vendor_token``).

The subject token and the access token are never logged.
"""

import typing

import pydantic

from imbi.common.plugins import identity

#: Fixed in code (D8). No tenant setting can change it.
TOKEN_URL = 'https://auth.openai.com/oauth/token'
_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:token-exchange'
_SUBJECT_TOKEN_TYPE = 'urn:ietf:params:oauth:token-type:jwt'

_Id = typing.Annotated[
    str,
    pydantic.StringConstraints(
        min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$'
    ),
]


class _Target(pydantic.BaseModel):
    """The OpenAI ids of one workload identity provider and account."""

    model_config = pydantic.ConfigDict(extra='forbid')

    identity_provider_id: _Id
    service_account_id: _Id


class OpenAIExchanger(identity.TokenExchanger):
    vendor = 'openai'
    label = 'OpenAI'
    target_help = (
        '{"identity_provider_id": "...", "service_account_id": "..."},'
        ' the ids from the OpenAI dashboard.'
    )
    #: The audience of the OpenAI workload identity provider. The
    #: provider in the OpenAI dashboard must use this value.
    audience = 'https://api.openai.com/v1'
    #: An OpenAI token never outlives its subject token. 3300 seconds
    #: keeps the ``aws_sts`` role session at 3600 seconds, the AWS
    #: limit for role chaining (imbi-api on IRSA or EKS Pod Identity).
    jwt_seconds = 3300

    def validate_target(
        self, target: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        return identity.validate_model(_Target, target)

    async def exchange(
        self, target: dict[str, typing.Any], identity_token: str
    ) -> identity.AccessToken:
        return await identity.post_exchange(
            'OpenAI',
            TOKEN_URL,
            {
                'grant_type': _GRANT_TYPE,
                'subject_token': identity_token,
                'subject_token_type': _SUBJECT_TOKEN_TYPE,
                **target,
            },
        )


EXCHANGER = OpenAIExchanger()


class OpenAIWif(identity.WifSecretProvider):
    """``openai_wif``: an OpenAI token for the agent of the task."""

    type = 'openai_wif'
    label = 'OpenAI workload identity'
    exchanger = EXCHANGER
