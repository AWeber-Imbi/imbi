"""Tests for the Anthropic client of each catalog AI Provider."""

import typing
import unittest
from unittest import mock

import anthropic

from imbi.common import models
from imbi.common.llm import clients, resolve, tokens

ORG = models.Organization(id='org-1', name='Acme', slug='acme')
WIF = models.AIProviderWorkloadIdentity(
    organization_id='org-1', target={'service_account_id': 's'}
)


def _provider(**overrides: typing.Any) -> models.AIProvider:
    return models.AIProvider.model_validate(
        {
            'id': 'prv-1',
            'name': 'Claude',
            'slug': 'claude',
            'driver': 'anthropic',
            'organization': ORG,
            **overrides,
        }
    )


def _clients(
    api_token: str = '', api_key: str | None = None
) -> clients.ProviderClients:
    return clients.ProviderClients(
        api_url='http://imbi-api:8000',
        api_token=api_token,
        api_key=api_key,
        client_class=anthropic.AsyncAnthropic,
    )


class ProviderClientsTestCase(unittest.IsolatedAsyncioTestCase):
    def test_workload_identity_gets_a_token_for_the_provider(self) -> None:
        # The workload identity wins over the key of the service.
        found = _clients('ik_1_s', 'sk-env')
        with mock.patch.object(
            tokens, 'ServiceToken', wraps=tokens.ServiceToken
        ) as source:
            client = found.get(_provider(workload_identity=WIF), 'ada@x')
        source.assert_called_once_with(
            'http://imbi-api:8000',
            'ik_1_s',
            provider='acme/claude',
            user='ada@x',
            org=None,
        )
        self.assertEqual(client.auth_token, 'imbi-ai-provider')

    def test_the_key_of_the_service_never_goes_to_a_custom_base_url(
        self,
    ) -> None:
        # An organization admin sets the base URL; the key of the service
        # is for all organizations.
        for api_token in ('', 'ik_1_s'):
            client_class = mock.Mock()
            found = clients.ProviderClients(
                api_url='http://imbi-api:8000',
                api_token=api_token,
                api_key='sk-env',
                client_class=client_class,
            )
            with (
                self.subTest(api_token=api_token),
                self.assertRaises(resolve.ModelUnusable) as raised,
            ):
                found.get(
                    _provider(base_url='https://llm.example.com'), 'ada@x'
                )
            self.assertEqual(
                raised.exception.reason, 'provider_credentials_unavailable'
            )
            self.assertIn('never sent', str(raised.exception))
            client_class.assert_not_called()

    def test_the_key_of_the_service_with_the_default_base_url(self) -> None:
        for base_url in (None, 'https://api.anthropic.com/'):
            with self.subTest(base_url=base_url):
                client = _clients('', 'sk-env').get(
                    _provider(base_url=base_url), 'ada@x'
                )
                self.assertEqual(client.api_key, 'sk-env')
                self.assertEqual(
                    str(client.base_url).rstrip('/'),
                    'https://api.anthropic.com',
                )

    def test_no_credential_is_an_error(self) -> None:
        for api_token, provider in (
            ('', _provider(workload_identity=WIF)),
            ('ik_1_s', _provider()),
        ):
            with (
                self.subTest(api_token=api_token),
                self.assertRaises(resolve.ModelUnusable) as raised,
            ):
                _clients(api_token).get(provider, 'ada@x')
            self.assertEqual(
                raised.exception.reason, 'provider_credentials_unavailable'
            )

    def test_one_client_for_each_provider_and_user(self) -> None:
        # Two users, interleaved: each keeps a client whose token is
        # minted for that user only.
        found = _clients('ik_1_s')
        provider = _provider(workload_identity=WIF)
        with mock.patch.object(
            tokens, 'ServiceToken', wraps=tokens.ServiceToken
        ) as source:
            ada = found.get(provider, 'ada@x')
            bob = found.get(provider, 'bob@x')
            self.assertIs(found.get(provider, 'ada@x'), ada)
            self.assertIs(found.get(provider, 'bob@x'), bob)
        self.assertIsNot(ada, bob)
        self.assertEqual(
            [c.kwargs['user'] for c in source.call_args_list],
            ['ada@x', 'bob@x'],
        )
        other = found.get(
            _provider(id='prv-2', slug='other', workload_identity=WIF),
            'ada@x',
        )
        self.assertIsNot(other, ada)

    def test_a_key_client_is_shared_by_users(self) -> None:
        # The key of the service does not depend on the user.
        found = _clients(api_key='sk-env')
        provider = _provider()
        self.assertIs(
            found.get(provider, 'ada@x'), found.get(provider, 'bob@x')
        )

    async def test_the_cache_is_bounded_and_closes_dropped_clients(
        self,
    ) -> None:
        found = _clients('ik_1_s')
        provider = _provider(workload_identity=WIF)
        first = found.get(provider, 'u0')
        with (
            mock.patch.object(clients, 'MAX_CLIENTS', 2),
            mock.patch.object(first, 'close', mock.AsyncMock()) as close,
        ):
            found.get(provider, 'u1')
            found.get(provider, 'u2')
            self.assertIsNot(found.get(provider, 'u0'), first)
            # A turn can still hold the dropped client.
            close.assert_not_awaited()
            await found.aclose()
        close.assert_awaited_once()

    def test_no_base_url_uses_the_driver_default(self) -> None:
        # Not ANTHROPIC_BASE_URL from the environment of the service.
        with mock.patch.dict(
            'os.environ', {'ANTHROPIC_BASE_URL': 'https://evil.example.com'}
        ):
            client = _clients('ik_1_s', 'sk-env').get(
                _provider(workload_identity=WIF), 'ada@x'
            )
        self.assertEqual(
            str(client.base_url).rstrip('/'), 'https://api.anthropic.com'
        )
