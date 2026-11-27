"""One Anthropic client for each catalog AI Provider (ADR 0018).

For the assistant and the Slack bot, which call Anthropic only. The
credential of a provider is, in this order:

1. Its workload identity: a token for that provider from imbi-api
   (``POST /ai-providers/token`` with the provider and the user). This
   needs the API token of the service.
2. The ``ANTHROPIC_API_KEY`` of the service, sent to the base URL of the
   provider.

With neither, the provider cannot be used.
"""

import typing

import anthropic

from imbi.common import graph, models
from imbi.common.llm import resolve, tokens

PROVIDER_QUERY: typing.LiteralString = """
MATCH (p:AIProvider {{slug: {slug}}})
      -[:BELONGS_TO]->(o:Organization {{slug: {org}}})
RETURN p, o
"""


def provider_ref(provider: models.AIProvider) -> str:
    """``<org-slug>/<provider-slug>``."""
    return f'{provider.organization.slug}/{provider.slug}'


async def fetch_provider(db: graph.Graph, ref: str) -> models.AIProvider:
    """Return the provider ``<org-slug>/<provider-slug>`` when an
    Anthropic client can use it.

    Raises:
        resolve.ModelUnusable: ``not_found``, ``provider_disabled``, or
            ``unsupported_driver``.

    """
    org, _, slug = ref.partition('/')
    records = await db.execute(
        PROVIDER_QUERY, {'org': org, 'slug': slug}, ['p', 'o']
    )
    if not records:
        raise resolve.ModelUnusable(
            'not_found', ref, f'AI provider {ref!r} is not in the catalog'
        )
    provider = models.AIProvider.model_validate(
        {
            **graph.parse_agtype(records[0]['p']),
            'organization': graph.parse_agtype(records[0]['o']),
        }
    )
    if not provider.enabled:
        raise resolve.ModelUnusable(
            'provider_disabled', ref, f'AI provider {ref!r} is disabled'
        )
    if provider.driver != 'anthropic':
        raise resolve.ModelUnusable(
            'unsupported_driver',
            ref,
            f'AI provider {ref!r} is not an anthropic provider',
        )
    return provider


class ProviderClients:
    """The cached clients of one service, one for each provider."""

    def __init__(
        self,
        *,
        api_url: str,
        api_token: str,
        api_key: str | None,
        client_class: type[anthropic.AsyncAnthropic],
    ) -> None:
        self._api_url = api_url
        self._api_token = api_token
        self._api_key = api_key
        self._client_class = client_class
        #: By provider id: the client, the token source, and the
        #: settings it was made with.
        self._clients: dict[
            str,
            tuple[
                anthropic.AsyncAnthropic,
                tokens.ServiceToken | None,
                tuple[str, bool, str | None],
            ],
        ] = {}

    def get(
        self, provider: models.AIProvider, user: str
    ) -> anthropic.AsyncAnthropic:
        """Return the client of ``provider`` for a call for ``user``.

        Raises:
            resolve.ModelUnusable: ``provider_credentials_unavailable``.

        """
        ref = provider_ref(provider)
        wif = provider.workload_identity is not None
        settings = (ref, wif, provider.base_url)
        found = self._clients.get(provider.id)
        if found is not None and found[2] == settings:
            if found[1] is not None:
                found[1].user = user
            return found[0]
        source: tokens.ServiceToken | None = None
        if wif and self._api_token:
            source = tokens.ServiceToken(
                self._api_url, self._api_token, provider=ref, user=user
            )
            client = tokens.bearer_client(
                source,
                client_class=self._client_class,
                base_url=provider.base_url,
            )
        elif self._api_key:
            client = self._client_class(
                api_key=self._api_key, base_url=provider.base_url
            )
        else:
            raise resolve.ModelUnusable(
                'provider_credentials_unavailable',
                ref,
                f'AI provider {ref!r} has no workload identity this service '
                'can use, and ANTHROPIC_API_KEY is not set',
            )
        # ponytail: a replaced client is not closed; its connections
        # close when it is collected. Close it if providers change often.
        self._clients[provider.id] = (client, source, settings)
        return client

    async def aclose(self) -> None:
        for client, _source, _settings in self._clients.values():
            await client.close()
        self._clients.clear()
