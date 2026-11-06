"""Tests for the AI Provider token cache (WIF plan 4.6)."""

import datetime
import unittest
from unittest import mock

from imbi.api.llm import tokens
from imbi.common import models
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
        self.cache = tokens.TokenCache()
        self.store = mock.AsyncMock()
        self.store.identity_source.return_value = SOURCE
        self.now = 1000.0
        self.minted = 0
        self.fail: contract.IdentityError | None = None
        for target, value in (
            ('time.monotonic', lambda: self.now),
            ('random.uniform', lambda a, b: 0),
        ):
            patcher = mock.patch(
                f'imbi.api.llm.tokens.{target}', side_effect=value
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch(
            'imbi.api.llm.tokens.identity.ai_provider_token', self._mint
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _mint(
        self, provider: models.AIProvider, setting: object
    ) -> contract.AccessToken:
        if self.fail is not None:
            raise self.fail
        self.minted += 1
        return contract.AccessToken(
            f'token-{self.minted}',
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=600),
        )

    async def test_reuses_then_renews_before_expiry(self) -> None:
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-1'
        )
        self.now += 400
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-1'
        )
        # 600 s lifetime: renew 120 s (20 percent) before expiry.
        self.now += 81
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-2'
        )

    async def test_failed_renewal_keeps_the_valid_token(self) -> None:
        await self.cache.get(self.store, _provider())
        self.now += 500
        self.fail = contract.IdentityError('unavailable', retryable=True)
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-1'
        )
        self.fail = None
        # The backoff (1 s) holds the next attempt.
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-1'
        )
        self.now += 1
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-2'
        )

    async def test_expired_token_is_not_returned(self) -> None:
        await self.cache.get(self.store, _provider())
        self.now += 600
        self.fail = contract.IdentityError('unavailable', retryable=True)
        with self.assertRaises(contract.IdentityError):
            await self.cache.get(self.store, _provider())

    async def test_invalidate_drops_only_the_current_token(self) -> None:
        await self.cache.get(self.store, _provider())
        self.cache.invalidate('prv-1', 'token-0')
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-1'
        )
        self.cache.invalidate('prv-1', 'token-1')
        self.assertEqual(
            await self.cache.get(self.store, _provider()), 'token-2'
        )

    async def test_a_changed_configuration_mints_again(self) -> None:
        await self.cache.get(self.store, _provider())
        other = _provider(service_account_id='svc-2')
        self.assertEqual(await self.cache.get(self.store, other), 'token-2')
        self.store.identity_source.return_value = {
            **SOURCE,
            'updated_at': '2026-11-07',
        }
        self.assertEqual(await self.cache.get(self.store, other), 'token-3')
