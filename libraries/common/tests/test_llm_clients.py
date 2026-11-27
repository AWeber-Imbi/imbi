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
        )
        self.assertEqual(client.auth_token, 'imbi-ai-provider')

    def test_the_key_of_the_service_with_the_provider_base_url(self) -> None:
        for api_token in ('', 'ik_1_s'):
            with self.subTest(api_token=api_token):
                client = _clients(api_token, 'sk-env').get(
                    _provider(base_url='https://llm.example.com'), 'ada@x'
                )
                self.assertEqual(client.api_key, 'sk-env')
                self.assertEqual(
                    str(client.base_url).rstrip('/'),
                    'https://llm.example.com',
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

    def test_one_client_for_each_provider(self) -> None:
        found = _clients('ik_1_s')
        provider = _provider(workload_identity=WIF)
        first = found.get(provider, 'ada@x')
        self.assertIs(found.get(provider, 'bob@x'), first)
        # The renewal names the user of the latest call.
        source = found._clients['prv-1'][1]
        assert source is not None
        self.assertEqual(source.user, 'bob@x')
        other = found.get(
            _provider(id='prv-2', slug='other', **{'workload_identity': WIF}),
            'ada@x',
        )
        self.assertIsNot(other, first)


class FetchProviderTestCase(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, rows: list[dict[str, typing.Any]]) -> typing.Any:
        db = mock.AsyncMock()
        db.execute.return_value = rows
        with mock.patch.object(
            clients.graph, 'parse_agtype', side_effect=lambda value: value
        ):
            return await clients.fetch_provider(db, 'acme/claude')

    def row(self, **overrides: typing.Any) -> list[dict[str, typing.Any]]:
        props = _provider(**overrides).model_dump(
            mode='json', exclude={'organization'}
        )
        return [{'p': props, 'o': ORG.model_dump(mode='json')}]

    async def test_found(self) -> None:
        provider = await self.fetch(self.row())
        self.assertEqual(clients.provider_ref(provider), 'acme/claude')

    async def test_errors(self) -> None:
        for rows, reason in (
            ([], 'not_found'),
            (self.row(enabled=False), 'provider_disabled'),
            (self.row(driver='openai'), 'unsupported_driver'),
        ):
            with (
                self.subTest(reason=reason),
                self.assertRaises(resolve.ModelUnusable) as raised,
            ):
                await self.fetch(rows)
            self.assertEqual(raised.exception.reason, reason)
