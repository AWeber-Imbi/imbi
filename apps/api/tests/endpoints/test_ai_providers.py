"""Tests for the org-scoped AI provider endpoints."""

import datetime
import typing
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.endpoints import ai_providers
from imbi.common import graph
from imbi.common.llm import discovery

ORG = 'acme'
BASE = f'/organizations/{ORG}/ai-providers'


class QueryRouter:
    """Dispatch ``db.execute`` calls by a substring of the query text.

    The provider endpoints issue several distinct queries per request
    (fetch, counts, uniqueness check, write), so a single
    ``return_value`` cannot express a scenario. Rules are matched in
    order and the first hit wins; an unmatched query returns ``[]``.
    """

    def __init__(self, *rules: tuple[str, typing.Any]) -> None:
        self.rules = list(rules)
        self.calls: list[tuple[str, dict[str, typing.Any]]] = []

    def __call__(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
        raw: bool = False,
    ) -> list[dict[str, typing.Any]]:
        """Return the rows for ``query``; used as an ``AsyncMock`` side effect.

        Deliberately synchronous: ``AsyncMock`` awaits on the caller's
        behalf and uses a plain side effect's return value as the awaited
        result.
        """
        self.calls.append((query, dict(params or {})))
        for needle, result in self.rules:
            if needle in query:
                return result
        return []

    def params_for(self, needle: str) -> dict[str, typing.Any]:
        """Return the params of the first recorded matching call."""
        for query, params in self.calls:
            if needle in query:
                return params
        raise AssertionError(f'no query matched {needle!r}')


# The read queries are matched by their exact template, because the
# update and delete queries embed the same ``MATCH`` and a substring
# rule would shadow them.
GET_PROVIDER = ai_providers._GET_QUERY
LIST_PROVIDERS = ai_providers._LIST_QUERY
SLUG_TAKEN = ai_providers._SLUG_TAKEN_QUERY
COUNTS = ai_providers._COUNTS_QUERY
CONFIGURED = ai_providers._CONFIGURED_QUERY
CREATE = 'CREATE (p:AIProvider'
UPDATE = 'SET p.'
DELETE = 'DETACH DELETE p'


def provider_props(**overrides: typing.Any) -> dict[str, typing.Any]:
    """Return a default AIProvider vertex property dict."""
    data: dict[str, typing.Any] = {
        'id': 'prv-1',
        'name': 'Anthropic',
        'slug': 'anthropic',
        'description': None,
        'icon': None,
        'driver': 'anthropic',
        'base_url': None,
        'enabled': True,
        'credentials_encrypted': None,
        'credential_hint': None,
        'credential_updated_at': None,
        'region': None,
        'project_id': None,
        'created_at': '2026-09-01T12:00:00Z',
        'updated_at': '2026-09-01T12:00:00Z',
    }
    data.update(overrides)
    return data


class AIProviderTestBase(support.SharedAppTestCase):
    """Shared fixture: admin principal, mocked graph, patched agtype."""

    is_admin = True

    def setUp(self) -> None:
        self.user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=self.is_admin,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = fastapi.testclient.TestClient(self.test_app)
        patcher = mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def route(self, *rules: tuple[str, typing.Any]) -> QueryRouter:
        """Install a :class:`QueryRouter` as the mocked ``execute``."""
        router = QueryRouter(*rules)
        self.mock_db.execute.side_effect = router
        return router

    def assert_scoped(
        self, router: QueryRouter, needle: str, org_slug: str
    ) -> None:
        """Assert a query ran and carried ``org_slug``.

        The router answers an unmatched query with ``[]``, so a cross-org
        test would pass even if the ``BELONGS_TO`` hop were dropped from
        the Cypher. Asserting the parameter reached the query is what
        makes those tests mean something.
        """
        self.assertEqual(router.params_for(needle)['org_slug'], org_slug)


class DriverCatalogTestCase(AIProviderTestBase):
    """The static driver catalog endpoint."""

    def test_lists_every_driver(self) -> None:
        """All five drivers are returned with their capability flags."""
        response = self.client.get('/ai-provider-drivers')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            {entry['slug'] for entry in data},
            {
                'anthropic',
                'openai',
                'openai_compatible',
                'bedrock',
                'vertex',
            },
        )
        by_slug = {entry['slug']: entry for entry in data}
        self.assertTrue(by_slug['openai_compatible']['requires_base_url'])
        self.assertTrue(by_slug['bedrock']['supports_iam'])
        self.assertFalse(by_slug['bedrock']['supports_discovery'])


class CreateProviderTestCase(AIProviderTestBase):
    """``POST /organizations/{org}/ai-providers``."""

    def test_create_encrypts_key_and_never_echoes_it(self) -> None:
        """The plaintext key is encrypted, hinted, and not returned."""
        stored = provider_props(
            credentials_encrypted='enc:sk-test-abcd',
            credential_hint='abcd',
            credential_updated_at='2026-09-01T12:00:00Z',
        )
        router = self.route((CREATE, [{'p': stored}]))
        with mock.patch(
            'imbi.api.endpoints.ai_providers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ) as enc:
            response = self.client.post(
                BASE + '/',
                json={
                    'name': 'Anthropic',
                    'driver': 'anthropic',
                    'api_key': 'sk-test-abcd',
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('sk-test-abcd', response.text)
        data = response.json()
        self.assertEqual(data['slug'], 'anthropic')
        self.assertEqual(data['credential_hint'], 'abcd')
        self.assertTrue(data['has_credentials'])
        self.assertEqual(data['auth_kind'], 'api_key')
        self.assertTrue(data['is_builtin_driver'])
        enc.assert_any_call('sk-test-abcd')
        persisted = router.params_for(CREATE)
        self.assertEqual(
            persisted['credentials_encrypted'], 'enc:sk-test-abcd'
        )
        self.assertNotIn('api_key', persisted)

    def test_create_without_key_reports_none(self) -> None:
        """A provider with no key and no IAM support has no auth."""
        self.route((CREATE, [{'p': provider_props()}]))
        response = self.client.post(
            BASE + '/', json={'name': 'Anthropic', 'driver': 'anthropic'}
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['auth_kind'], 'none')
        self.assertFalse(data['has_credentials'])

    def test_bedrock_without_key_reports_iam(self) -> None:
        """A bedrock provider falls back to ambient IAM credentials."""
        self.route(
            (
                CREATE,
                [
                    {
                        'p': provider_props(
                            driver='bedrock',
                            name='Bedrock',
                            slug='bedrock',
                            region='us-east-1',
                        )
                    }
                ],
            )
        )
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'Bedrock',
                'driver': 'bedrock',
                'region': 'us-east-1',
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['auth_kind'], 'iam')

    def test_openai_compatible_requires_base_url(self) -> None:
        """``openai_compatible`` has no default endpoint to fall back on."""
        self.route()
        response = self.client.post(
            BASE + '/', json={'name': 'vLLM', 'driver': 'openai_compatible'}
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_non_http_base_url(self) -> None:
        """Only http and https are accepted."""
        self.route()
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'vLLM',
                'driver': 'openai_compatible',
                'base_url': 'file:///etc/passwd',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_base_url_with_userinfo(self) -> None:
        """A base URL must not smuggle credentials."""
        self.route()
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'vLLM',
                'driver': 'openai_compatible',
                'base_url': 'https://key@vllm.example.com/v1',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_accepts_valid_base_url(self) -> None:
        """A plain https endpoint is accepted and is not built-in."""
        self.route(
            (
                CREATE,
                [
                    {
                        'p': provider_props(
                            driver='openai_compatible',
                            name='vLLM',
                            slug='vllm',
                            base_url='https://vllm.example.com/v1',
                        )
                    }
                ],
            )
        )
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'vLLM',
                'driver': 'openai_compatible',
                'base_url': 'https://vllm.example.com/v1',
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()['is_builtin_driver'])

    def test_duplicate_slug_in_org_conflicts(self) -> None:
        """Slugs are unique per organization."""
        self.route((SLUG_TAKEN, [{'id': 'prv-other'}]))
        response = self.client.post(
            BASE + '/', json={'name': 'Anthropic', 'driver': 'anthropic'}
        )
        self.assertEqual(response.status_code, 409)

    def test_unknown_organization_is_404(self) -> None:
        """A create against a missing organization matches nothing."""
        self.route()
        response = self.client.post(
            BASE + '/', json={'name': 'Anthropic', 'driver': 'anthropic'}
        )
        self.assertEqual(response.status_code, 404)


class ReadProviderTestCase(AIProviderTestBase):
    """``GET`` list and detail."""

    def test_list_carries_model_counts(self) -> None:
        """Counts come from the models each provider serves."""
        self.route(
            (LIST_PROVIDERS, [{'p': provider_props()}]),
            (
                COUNTS,
                [
                    {'provider_id': 'prv-1', 'enabled': True},
                    {'provider_id': 'prv-1', 'enabled': False},
                ],
            ),
        )
        response = self.client.get(BASE + '/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['model_count'], 2)
        self.assertEqual(data[0]['enabled_model_count'], 1)

    def test_list_is_ordered_by_name(self) -> None:
        """Providers come back alphabetically."""
        self.route(
            (
                LIST_PROVIDERS,
                [
                    {'p': provider_props(id='b', name='Zeta', slug='zeta')},
                    {'p': provider_props(id='a', name='Alpha', slug='alpha')},
                ],
            )
        )
        response = self.client.get(BASE + '/')
        self.assertEqual(
            [entry['name'] for entry in response.json()], ['Alpha', 'Zeta']
        )

    def test_get_returns_provider(self) -> None:
        """A provider in this organization is returned."""
        self.route((GET_PROVIDER, [{'p': provider_props()}]))
        response = self.client.get(f'{BASE}/prv-1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], 'prv-1')

    def test_get_scopes_query_to_org(self) -> None:
        """The organization slug is part of the match."""
        router = self.route((GET_PROVIDER, [{'p': provider_props()}]))
        self.client.get(f'{BASE}/prv-1')
        self.assertEqual(router.params_for(GET_PROVIDER)['org_slug'], ORG)

    def test_get_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.get('/organizations/other/ai-providers/prv-1')
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class PatchProviderTestCase(AIProviderTestBase):
    """``PATCH`` with RFC 6902 operations."""

    def test_rename(self) -> None:
        """A replace on /name is persisted."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (UPDATE, [{'p': provider_props(name='Claude')}]),
        )
        response = self.client.patch(
            f'{BASE}/prv-1',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Claude'}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Claude')
        self.assertEqual(router.params_for(UPDATE)['name'], 'Claude')

    def test_patch_preserves_credentials(self) -> None:
        """An unrelated patch leaves the stored key untouched."""
        existing = provider_props(
            credentials_encrypted='enc:old', credential_hint='9999'
        )
        router = self.route(
            (GET_PROVIDER, [{'p': existing}]),
            (UPDATE, [{'p': existing}]),
        )
        response = self.client.patch(
            f'{BASE}/prv-1',
            json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            router.params_for(UPDATE)['credentials_encrypted'], 'enc:old'
        )
        self.assertEqual(response.json()['credential_hint'], '9999')

    def test_patch_rejects_a_credential_path(self) -> None:
        """A patch aimed at credential state is refused, not ignored."""
        for path in (
            '/credentials_encrypted',
            '/credential_hint',
            '/credential_updated_at',
        ):
            with self.subTest(path=path):
                self.route((GET_PROVIDER, [{'p': provider_props()}]))
                response = self.client.patch(
                    f'{BASE}/prv-1',
                    json=[{'op': 'add', 'path': path, 'value': 'x'}],
                )
                self.assertEqual(response.status_code, 400)

    def test_patch_rejects_a_derived_path(self) -> None:
        """Derived response fields are not writable either."""
        self.route((GET_PROVIDER, [{'p': provider_props()}]))
        response = self.client.patch(
            f'{BASE}/prv-1',
            json=[{'op': 'add', 'path': '/model_count', 'value': 99}],
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_slug_collision_conflicts(self) -> None:
        """Renaming onto another provider's slug is a conflict."""
        self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (SLUG_TAKEN, [{'id': 'prv-2'}]),
        )
        response = self.client.patch(
            f'{BASE}/prv-1',
            json=[{'op': 'replace', 'path': '/slug', 'value': 'openai'}],
        )
        self.assertEqual(response.status_code, 409)

    def test_patch_invalid_base_url_is_422(self) -> None:
        """A patched base URL is validated like a created one."""
        self.route((GET_PROVIDER, [{'p': provider_props()}]))
        response = self.client.patch(
            f'{BASE}/prv-1',
            json=[
                {
                    'op': 'replace',
                    'path': '/base_url',
                    'value': 'ftp://example.com',
                }
            ],
        )
        self.assertEqual(response.status_code, 422)

    def test_patch_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.patch(
            '/organizations/other/ai-providers/prv-1',
            json=[{'op': 'replace', 'path': '/name', 'value': 'X'}],
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class DeleteProviderTestCase(AIProviderTestBase):
    """``DELETE`` and its no-cascade rule."""

    def test_delete_without_models(self) -> None:
        """An unreferenced provider is removed."""
        self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (DELETE, [{'p': provider_props()}]),
        )
        response = self.client.delete(f'{BASE}/prv-1')
        self.assertEqual(response.status_code, 204)

    def test_delete_with_models_conflicts(self) -> None:
        """A provider that still serves models cannot be deleted."""
        self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (COUNTS, [{'provider_id': 'prv-1', 'enabled': True}]),
        )
        response = self.client.delete(f'{BASE}/prv-1')
        self.assertEqual(response.status_code, 409)

    def test_delete_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.delete(
            '/organizations/other/ai-providers/prv-1'
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class CredentialsTestCase(AIProviderTestBase):
    """``PUT`` / ``DELETE`` on the credentials sub-resource."""

    def test_put_sets_ciphertext_hint_and_timestamp(self) -> None:
        """All three credential fields are written together."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (
                UPDATE,
                [
                    {
                        'p': provider_props(
                            credentials_encrypted='enc:sk-live-wxyz',
                            credential_hint='wxyz',
                            credential_updated_at='2026-09-04T00:00:00Z',
                        )
                    }
                ],
            ),
        )
        with mock.patch(
            'imbi.api.endpoints.ai_providers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.put(
                f'{BASE}/prv-1/credentials',
                json={'api_key': 'sk-live-wxyz'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('sk-live-wxyz', response.text)
        data = response.json()
        self.assertEqual(data['credential_hint'], 'wxyz')
        self.assertTrue(data['has_credentials'])
        persisted = router.params_for(UPDATE)
        self.assertEqual(
            persisted['credentials_encrypted'], 'enc:sk-live-wxyz'
        )
        self.assertEqual(persisted['credential_hint'], 'wxyz')
        self.assertIsNotNone(persisted['credential_updated_at'])

    def test_short_key_stores_no_hint(self) -> None:
        """Four trailing characters of a short key is too much of it."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (UPDATE, [{'p': provider_props()}]),
        )
        with mock.patch(
            'imbi.api.endpoints.ai_providers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.put(
                f'{BASE}/prv-1/credentials', json={'api_key': 'sk-123'}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(router.params_for(UPDATE)['credential_hint'])
        self.assertIsNotNone(
            router.params_for(UPDATE)['credentials_encrypted']
        )

    def test_put_rejects_empty_key(self) -> None:
        """An empty key is a validation error, not a silent clear."""
        self.route((GET_PROVIDER, [{'p': provider_props()}]))
        response = self.client.put(
            f'{BASE}/prv-1/credentials', json={'api_key': ''}
        )
        self.assertEqual(response.status_code, 422)

    def test_delete_clears_all_three_fields(self) -> None:
        """Removing a key clears its ciphertext, hint, and timestamp."""
        router = self.route(
            (
                GET_PROVIDER,
                [
                    {
                        'p': provider_props(
                            credentials_encrypted='enc:old',
                            credential_hint='9999',
                            credential_updated_at='2026-09-01T12:00:00Z',
                        )
                    }
                ],
            ),
            (UPDATE, [{'p': provider_props()}]),
        )
        response = self.client.delete(f'{BASE}/prv-1/credentials')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['has_credentials'])
        self.assertIsNone(data['credential_hint'])
        persisted = router.params_for(UPDATE)
        self.assertIsNone(persisted['credentials_encrypted'])
        self.assertIsNone(persisted['credential_hint'])
        self.assertIsNone(persisted['credential_updated_at'])

    def test_put_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.put(
            '/organizations/other/ai-providers/prv-1/credentials',
            json={'api_key': 'sk-test-1234'},
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')

    def test_delete_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.delete(
            '/organizations/other/ai-providers/prv-1/credentials'
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class DiscoveryTestCase(AIProviderTestBase):
    """``POST /{id}/discover``."""

    def test_requires_credentials(self) -> None:
        """Discovery needs a stored key to authenticate with."""
        self.route((GET_PROVIDER, [{'p': provider_props()}]))
        response = self.client.post(f'{BASE}/prv-1/discover')
        self.assertEqual(response.status_code, 409)

    def test_rejects_driver_without_discovery(self) -> None:
        """Bedrock has no list-models support in this iteration."""
        self.route(
            (
                GET_PROVIDER,
                [
                    {
                        'p': provider_props(
                            driver='bedrock',
                            credentials_encrypted='enc:key',
                        )
                    }
                ],
            )
        )
        response = self.client.post(f'{BASE}/prv-1/discover')
        self.assertEqual(response.status_code, 422)

    def test_provider_failure_is_502_without_the_key(self) -> None:
        """A failing call surfaces a sanitized message."""
        self.route(
            (
                GET_PROVIDER,
                [{'p': provider_props(credentials_encrypted='enc:key')}],
            )
        )
        with (
            mock.patch(
                'imbi.api.endpoints.ai_providers.decrypt_config_value',
                return_value='sk-secret-1234',
            ),
            mock.patch(
                'imbi.common.llm.discovery.list_models',
                new_callable=mock.AsyncMock,
                side_effect=discovery.DiscoveryError(
                    'The anthropic endpoint returned HTTP 401'
                ),
            ),
        ):
            response = self.client.post(f'{BASE}/prv-1/discover')
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('sk-secret-1234', response.text)
        self.assertIn('HTTP 401', response.json()['detail'])

    def test_flags_already_configured_models(self) -> None:
        """Models already in the catalog are marked, not filtered out."""
        self.route(
            (
                GET_PROVIDER,
                [{'p': provider_props(credentials_encrypted='enc:key')}],
            ),
            (CONFIGURED, [{'model_id': 'claude-opus-5'}]),
        )
        found = [
            discovery.DiscoveredModel(
                model_id='claude-opus-5',
                display_name='Claude Opus 5',
                context_window=200000,
                max_output_tokens=64000,
            ),
            discovery.DiscoveredModel(
                model_id='claude-haiku-4-5',
                display_name='Claude Haiku 4.5',
            ),
        ]
        with (
            mock.patch(
                'imbi.api.endpoints.ai_providers.decrypt_config_value',
                return_value='sk-secret-1234',
            ),
            mock.patch(
                'imbi.common.llm.discovery.list_models',
                new_callable=mock.AsyncMock,
                return_value=found,
            ),
        ):
            response = self.client.post(f'{BASE}/prv-1/discover')
        self.assertEqual(response.status_code, 200)
        data = response.json()['models']
        self.assertEqual(
            {entry['model_id']: entry['already_configured'] for entry in data},
            {'claude-opus-5': True, 'claude-haiku-4-5': False},
        )
        self.assertEqual(data[0]['context_window'], 200000)

    def test_discover_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.post(
            '/organizations/other/ai-providers/prv-1/discover'
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class ProviderPermissionTestCase(AIProviderTestBase):
    """Permission enforcement for a non-admin principal."""

    is_admin = False

    def test_list_denied(self) -> None:
        """Listing needs ai_model:read."""
        self.route()
        self.assertEqual(self.client.get(BASE + '/').status_code, 403)

    def test_drivers_denied(self) -> None:
        """The driver catalog needs ai_model:read."""
        self.assertEqual(
            self.client.get('/ai-provider-drivers').status_code, 403
        )

    def test_create_denied(self) -> None:
        """Creating needs ai_model:create."""
        self.route()
        response = self.client.post(
            BASE + '/', json={'name': 'Anthropic', 'driver': 'anthropic'}
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_denied(self) -> None:
        """Deleting needs ai_model:delete."""
        self.route()
        self.assertEqual(self.client.delete(f'{BASE}/prv-1').status_code, 403)

    def test_update_does_not_imply_credentials(self) -> None:
        """``ai_model:update`` must not grant key replacement."""
        self.auth_context.permissions = {'ai_model:update', 'ai_model:read'}
        self.route((GET_PROVIDER, [{'p': provider_props()}]))
        response = self.client.put(
            f'{BASE}/prv-1/credentials', json={'api_key': 'sk-1234'}
        )
        self.assertEqual(response.status_code, 403)

    def test_credentials_permission_allows_the_write(self) -> None:
        """``ai_model:credentials`` is what unlocks the route."""
        self.auth_context.permissions = {'ai_model:credentials'}
        self.route(
            (GET_PROVIDER, [{'p': provider_props()}]),
            (UPDATE, [{'p': provider_props(credential_hint='1234')}]),
        )
        with mock.patch(
            'imbi.api.endpoints.ai_providers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.put(
                f'{BASE}/prv-1/credentials', json={'api_key': 'sk-1234'}
            )
        self.assertEqual(response.status_code, 200)

    def test_read_permission_allows_listing(self) -> None:
        """``ai_model:read`` is enough to list."""
        self.auth_context.permissions = {'ai_model:read'}
        self.route()
        self.assertEqual(self.client.get(BASE + '/').status_code, 200)
