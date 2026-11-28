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

import collections

import anthropic

from imbi.common import models
from imbi.common.llm import resolve, tokens


def provider_ref(provider: models.AIProvider) -> str:
    """``<org-slug>/<provider-slug>``."""
    return f'{provider.organization.slug}/{provider.slug}'


#: The most clients that :class:`ProviderClients` keeps.
MAX_CLIENTS = 256


class ProviderClients:
    """The cached clients of one service, one for each provider and user.

    A workload identity token is minted for one user (imbi-api checks the
    organizations of that user), so a client is never shared between
    users.
    """

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
        #: By provider id and user, oldest use first: the client and the
        #: settings it was made with.
        self._clients: collections.OrderedDict[
            tuple[str, str, str | None],
            tuple[anthropic.AsyncAnthropic, tuple[str, bool, str | None]],
        ] = collections.OrderedDict()

    def get(
        self, provider: models.AIProvider, user: str, org: str | None = None
    ) -> anthropic.AsyncAnthropic:
        """Return the client of ``provider`` for a call for ``user``.
        ``org`` is the slug of the organization of the call, which a
        workload identity token request names (the slackbot sets it).

        Raises:
            resolve.ModelUnusable: ``provider_credentials_unavailable``.

        """
        ref = provider_ref(provider)
        wif = provider.workload_identity is not None
        settings = (ref, wif, provider.base_url)
        key = (provider.id, user, org)
        found = self._clients.get(key)
        if found is not None and found[1] == settings:
            self._clients.move_to_end(key)
            return found[0]
        if wif and self._api_token:
            client = tokens.bearer_client(
                tokens.ServiceToken(
                    self._api_url,
                    self._api_token,
                    provider=ref,
                    user=user,
                    org=org,
                ),
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
        # ponytail: a replaced or dropped client is not closed, because a
        # turn can still use it; its connections close when it is
        # collected. Close it after its last use if that leaks sockets.
        self._clients[key] = (client, settings)
        self._clients.move_to_end(key)
        while len(self._clients) > MAX_CLIENTS:
            self._clients.popitem(last=False)
        return client

    async def aclose(self) -> None:
        for client, _settings in self._clients.values():
            await client.close()
        self._clients.clear()
