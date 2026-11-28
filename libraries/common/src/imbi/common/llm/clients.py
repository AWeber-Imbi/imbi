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

import asyncio
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
    """The cached clients of one service.

    A workload identity token is minted for one user (imbi-api checks the
    organizations of that user), so such a client is for one user. A
    client with the key of the service is for every user of the provider.
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
        #: By provider id, user, and organization (``None`` for a client
        #: with the key of the service), oldest use first: the client and
        #: the settings it was made with.
        self._clients: collections.OrderedDict[
            tuple[str, str | None, str | None],
            tuple[anthropic.AsyncAnthropic, tuple[str, bool, str | None]],
        ] = collections.OrderedDict()
        #: Closes of dropped clients that are still running.
        self._closing: set[asyncio.Task[None]] = set()

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
        token = provider.workload_identity is not None and bool(
            self._api_token
        )
        settings = (ref, token, provider.base_url)
        key = (provider.id, user, org) if token else (provider.id, None, None)
        found = self._clients.get(key)
        if found is not None:
            if found[1] == settings:
                self._clients.move_to_end(key)
                return found[0]
            self._close(found[0])
        if token:
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
        self._clients[key] = (client, settings)
        self._clients.move_to_end(key)
        while len(self._clients) > MAX_CLIENTS:
            self._close(self._clients.popitem(last=False)[1][0])
        return client

    def _close(self, client: anthropic.AsyncAnthropic) -> None:
        """Close a dropped client in the background.

        ponytail: a turn that still holds the client gets a closed
        connection pool; count the users of a client if that happens.
        """
        task = asyncio.get_running_loop().create_task(client.close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def aclose(self) -> None:
        for client, _settings in self._clients.values():
            await client.close()
        self._clients.clear()
        await asyncio.gather(*self._closing)
