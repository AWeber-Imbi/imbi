"""Tests for the secret provider registry of the broker (ADR 0022, 9.7).

The providers themselves are tested in their plugins
(``plugins/aws/tests/test_secrets_manager.py``,
``plugins/github/tests/test_secret_provider.py``).
"""

import typing
import unittest
from unittest import mock

from imbi.api.secret_broker import providers
from imbi.common.plugins import secrets


class _Provider(secrets.SecretProvider):
    type = 'test_provider'
    label = 'Test'
    capabilities = frozenset[secrets.SecretCapability]({'static_retrieval'})


class _Other(secrets.SecretProvider):
    type = 'test_provider'
    label = 'Other'
    capabilities = frozenset[secrets.SecretCapability]()


def _entry(slug: str, *classes: type) -> mock.Mock:
    return mock.Mock(
        **{'manifest.slug': slug, 'manifest.secret_providers': list(classes)}
    )


class RegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(providers.PROVIDERS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_plugin_providers_load_on_first_use(self) -> None:
        with mock.patch.object(
            providers.plugin_registry,
            'list_plugins',
            return_value=[_entry('a', _Provider), _entry('b', _Other)],
        ):
            provider = providers.get('test_provider')
            # A second plugin cannot replace the type.
            self.assertIsInstance(provider, _Provider)
            self.assertIs(providers.get('test_provider'), provider)
            self.assertIn(provider, providers.all_providers())
        # The provider reaches the broker through its host.
        host = typing.cast(typing.Any, provider).host
        self.assertTrue(callable(host.provider_key))
        self.assertTrue(callable(host.check_provider_key))

    def test_unknown_type(self) -> None:
        with (
            mock.patch.object(
                providers.plugin_registry, 'list_plugins', return_value=[]
            ),
            self.assertRaises(providers.BrokerError) as ctx,
        ):
            providers.get('vault')
        self.assertEqual(ctx.exception.code, 'operation_not_supported')

    def test_graph_unavailable(self) -> None:
        from imbi.api import lifespans

        with (
            mock.patch.object(lifespans, '_graph', None),
            self.assertRaises(providers.BrokerError) as ctx,
        ):
            providers._Host().graph()  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(ctx.exception.reason, 'graph_unavailable')

    def test_error_codes(self) -> None:
        self.assertEqual(len(providers.ERROR_STATUS), 18)
        self.assertTrue(
            providers.BrokerError('secret_provider_unavailable').retryable
        )
        with self.assertRaises(ValueError):
            providers.BrokerError('not_a_code')
