"""Tests for the AI Provider token cache of imbi-api (WIF plan 4.6).

The renewal rules are tested in ``imbi-common`` (``test_llm_tokens``).
"""

import datetime
import unittest
from unittest import mock

from imbi.api.llm import tokens
from imbi.common import models
from imbi.common.llm import tokens as common_tokens
from imbi.common.plugins import identity as contract

SOURCE = {'type': 'fake', 'config': {}, 'updated_at': '2026-11-06'}


def _provider(**target: str) -> models.AIProvider:
    return models.AIProvider(
        id='prv-1',
        name='Anthropic',
        slug='anthropic',
        driver='anthropic',
        workload_identity=models.AIProviderWorkloadIdentity(
            organization_id='org-1',
            target=target or {'service_account_id': 'svc-1'},
        ),
    )


class TokenCacheTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        cache = mock.patch.object(tokens, 'CACHE', common_tokens.TokenCache())
        cache.start()
        self.addCleanup(cache.stop)
        self.store = mock.AsyncMock()
        self.store.identity_source.return_value = SOURCE
        self.minted = 0
        patcher = mock.patch(
            'imbi.api.llm.tokens.identity.ai_provider_token', self._mint
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _mint(
        self, provider: models.AIProvider, setting: object
    ) -> contract.AccessToken:
        self.minted += 1
        return contract.AccessToken(
            f'token-{self.minted}',
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=600),
        )

    async def _get(self, provider: models.AIProvider) -> str:
        return (await tokens.get(self.store, provider)).token

    async def test_a_changed_configuration_mints_again(self) -> None:
        self.assertEqual(await self._get(_provider()), 'token-1')
        self.assertEqual(await self._get(_provider()), 'token-1')
        other = _provider(service_account_id='svc-2')
        self.assertEqual(await self._get(other), 'token-2')
        self.store.identity_source.return_value = {
            **SOURCE,
            'updated_at': '2026-11-07',
        }
        self.assertEqual(await self._get(other), 'token-3')

    async def test_no_workload_identity(self) -> None:
        provider = _provider()
        provider.workload_identity = None
        with self.assertRaises(contract.IdentityError) as ctx:
            await tokens.get(self.store, provider)
        self.assertEqual(
            ctx.exception.reason, 'workload_identity_not_configured'
        )

    async def test_call_retries_once_after_401(self) -> None:
        seen: list[str] = []

        async def fn(token: str) -> str:
            seen.append(token)
            if len(seen) == 1:
                raise PermissionError
            return token

        result = await tokens.call(
            self.store,
            _provider(),
            fn,
            lambda exc: isinstance(exc, PermissionError),
        )
        self.assertEqual(result, 'token-2')
        self.assertEqual(seen, ['token-1', 'token-2'])

    async def test_provider_token_reads_the_provider(self) -> None:
        db = mock.Mock()
        with mock.patch(
            'imbi.api.endpoints.ai_providers.fetch_provider',
            mock.AsyncMock(return_value=_provider()),
        ) as fetch:
            source = tokens.ProviderToken(
                'prv-1', lambda: db, lambda: self.store
            )
            self.assertEqual(await source.get(), 'token-1')
            source.invalidate('token-1')
            self.assertEqual(await source.get(), 'token-2')
        fetch.assert_awaited_with(db, 'prv-1')

    async def test_provider_token_without_graph(self) -> None:
        source = tokens.ProviderToken(
            'prv-1', lambda: None, lambda: self.store
        )
        with self.assertRaises(contract.IdentityError) as ctx:
            await source.get()
        self.assertTrue(ctx.exception.retryable)
