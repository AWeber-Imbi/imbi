"""Tests for identity hydration helpers."""

import datetime
import unittest
from unittest import mock

from imbi_common.plugins.errors import PluginNotFoundError

from imbi_api.identity import errors as identity_errors
from imbi_api.identity import resolution


class IsActiveTestCase(unittest.TestCase):
    """Verify is_active distinguishes expired from live tokens."""

    def test_none_is_active(self) -> None:
        self.assertTrue(resolution.is_active(None))

    def test_future_expiry_is_active(self) -> None:
        future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            minutes=5
        )
        self.assertTrue(resolution.is_active(future))

    def test_past_expiry_is_inactive(self) -> None:
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=5
        )
        self.assertFalse(resolution.is_active(past))


class StartUrlForTestCase(unittest.TestCase):
    """Verify the canonical start-URL builder."""

    def test_builds_canonical_url(self) -> None:
        self.assertEqual(
            resolution._start_url_for('integration-7'),
            '/me/identities/integration-7/start',
        )


def _integration(
    *,
    plugin: str = 'oidc',
    encrypted_credentials: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        'id': 'integration-1',
        'plugin': plugin,
        'encrypted_credentials': encrypted_credentials or {},
        'capabilities': {},
    }


class HydrateIdentityTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify hydrate_identity loads a connection and materializes it."""

    def setUp(self) -> None:
        self.db = mock.AsyncMock()
        self.ctx = mock.MagicMock()
        self.ctx.actor_user_id = 'user-1'
        self.ctx.model_copy = mock.MagicMock(
            side_effect=lambda update: ('ctx-with', update)
        )

    async def test_missing_actor_raises_identity_required(self) -> None:
        self.ctx.actor_user_id = None
        with self.assertRaises(identity_errors.IdentityRequiredError) as cm:
            await resolution.hydrate_identity(
                self.db, self.ctx, 'integration-1'
            )
        self.assertEqual(cm.exception.integration_id, 'integration-1')
        self.assertEqual(
            cm.exception.start_url, '/me/identities/integration-1/start'
        )

    async def test_no_connection_raises_identity_required(self) -> None:
        with mock.patch.object(
            resolution.repository,
            'load_connection',
            new=mock.AsyncMock(return_value=None),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'integration-1'
                )

    async def test_inactive_connection_raises_identity_required(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'expired'
        connection.expires_at = None
        connection.refresh_token = None
        with mock.patch.object(
            resolution.repository,
            'load_connection',
            new=mock.AsyncMock(return_value=connection),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'integration-1'
                )

    async def test_missing_integration_raises_identity_required(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.expires_at = None
        connection.refresh_token = None
        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                'load_integration',
                new=mock.AsyncMock(return_value=None),
            ),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'integration-1'
                )

    async def test_capability_not_found_raises_identity_required(
        self,
    ) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.expires_at = None
        connection.refresh_token = None
        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                'load_integration',
                new=mock.AsyncMock(return_value=_integration()),
            ),
            mock.patch.object(
                resolution,
                'get_capability',
                side_effect=PluginNotFoundError('oidc'),
            ),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'integration-1'
                )

    async def test_proactive_refresh_when_near_expiry(self) -> None:
        # expires_at is 10 seconds from now → inside the 60s window.
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.access_token = 'old-access'
        connection.refresh_token = 'refresh'
        connection.expires_at = datetime.datetime.now(
            datetime.UTC
        ) + datetime.timedelta(seconds=10)
        connection.scopes = []

        refreshed = mock.MagicMock()
        refreshed.status = 'active'
        refreshed.access_token = 'new-access'
        refreshed.refresh_token = 'refresh-2'
        refreshed.expires_at = datetime.datetime.now(
            datetime.UTC
        ) + datetime.timedelta(hours=1)
        refreshed.scopes = []

        load = mock.AsyncMock(side_effect=[connection, refreshed])
        materialized = mock.MagicMock(name='materialized')
        handler = mock.MagicMock()
        handler.materialize = mock.AsyncMock(return_value=materialized)
        handler_cls = mock.MagicMock(return_value=handler)

        # Patch the lazy import target inside imbi_api.identity.flows.
        from imbi_api.identity import flows

        with (
            mock.patch.object(resolution.repository, 'load_connection', load),
            mock.patch.object(
                resolution,
                'load_integration',
                new=mock.AsyncMock(return_value=_integration()),
            ),
            mock.patch.object(
                resolution, 'get_capability', return_value=handler_cls
            ),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(return_value=mock.MagicMock()),
            ) as refresh_mock,
        ):
            await resolution.hydrate_identity(
                self.db, self.ctx, 'integration-1'
            )

        refresh_mock.assert_awaited_once()
        # The materialized credentials should derive from the refreshed
        # connection (post-refresh access token), not the stale one.
        base_credentials = handler.materialize.await_args[0][2]
        self.assertEqual(base_credentials.access_token, 'new-access')

    async def test_no_proactive_refresh_when_far_from_expiry(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.access_token = 'access'
        connection.refresh_token = 'refresh'
        connection.expires_at = datetime.datetime.now(
            datetime.UTC
        ) + datetime.timedelta(hours=1)
        connection.scopes = []

        materialized = mock.MagicMock(name='materialized')
        handler = mock.MagicMock()
        handler.materialize = mock.AsyncMock(return_value=materialized)
        handler_cls = mock.MagicMock(return_value=handler)

        from imbi_api.identity import flows

        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                'load_integration',
                new=mock.AsyncMock(return_value=_integration()),
            ),
            mock.patch.object(
                resolution, 'get_capability', return_value=handler_cls
            ),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(),
            ) as refresh_mock,
        ):
            await resolution.hydrate_identity(
                self.db, self.ctx, 'integration-1'
            )

        refresh_mock.assert_not_awaited()

    async def test_proactive_refresh_failure_maps_to_identity_required(
        self,
    ) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.refresh_token = 'refresh'
        connection.expires_at = datetime.datetime.now(
            datetime.UTC
        ) - datetime.timedelta(seconds=5)

        from imbi_api.identity import flows

        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(
                    side_effect=identity_errors.IdentityRefreshFailed('nope')
                ),
            ),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'integration-1'
                )

    async def test_happy_path_calls_materialize(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.access_token = 'access'
        connection.refresh_token = 'refresh'
        connection.expires_at = None
        connection.scopes = ['email']

        materialized = mock.MagicMock(name='materialized')
        handler = mock.MagicMock()
        handler.materialize = mock.AsyncMock(return_value=materialized)
        handler_cls = mock.MagicMock(return_value=handler)

        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                'load_integration',
                new=mock.AsyncMock(return_value=_integration()),
            ),
            mock.patch.object(
                resolution, 'get_capability', return_value=handler_cls
            ),
            mock.patch.object(
                resolution,
                'capability_state',
                return_value={'options': {'k': 'v'}},
            ),
        ):
            result = await resolution.hydrate_identity(
                self.db, self.ctx, 'integration-1'
            )

        # ctx.model_copy is patched to capture the update kwargs.
        self.assertEqual(result, ('ctx-with', {'identity': materialized}))
        handler.materialize.assert_awaited_once()
        # The new identity_options + db kwargs are forwarded.
        _args, kwargs = handler.materialize.call_args
        self.assertEqual(kwargs.get('identity_options'), {'k': 'v'})
        self.assertIs(kwargs.get('db'), self.db)

    async def test_explicit_identity_options_skip_capability_state(
        self,
    ) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.access_token = 'access'
        connection.refresh_token = 'refresh'
        connection.expires_at = None
        connection.scopes = ['email']

        materialized = mock.MagicMock(name='materialized')
        handler = mock.MagicMock()
        handler.materialize = mock.AsyncMock(return_value=materialized)
        handler_cls = mock.MagicMock(return_value=handler)

        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                'load_integration',
                new=mock.AsyncMock(return_value=_integration()),
            ),
            mock.patch.object(
                resolution, 'get_capability', return_value=handler_cls
            ),
        ):
            await resolution.hydrate_identity(
                self.db,
                self.ctx,
                'integration-1',
                identity_options={'explicit': True},
            )

        _args, kwargs = handler.materialize.call_args
        self.assertEqual(kwargs.get('identity_options'), {'explicit': True})


class LoadIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify load_integration parses and hydrates the Integration row."""

    async def test_returns_none_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await resolution.load_integration(db, 'integration-1')
        self.assertIsNone(result)

    async def test_returns_hydrated_integration(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'i': '{"id": "integration-1"}'}]
        with (
            mock.patch.object(
                resolution.graph,
                'parse_agtype',
                return_value={'id': 'integration-1'},
            ),
            mock.patch.object(
                resolution,
                'hydrate_integration',
                side_effect=lambda props: {**props, 'hydrated': True},
            ),
        ):
            result = await resolution.load_integration(db, 'integration-1')
        self.assertEqual(result, {'id': 'integration-1', 'hydrated': True})

    async def test_returns_none_when_parsed_value_not_dict(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'i': 'null'}]
        with mock.patch.object(
            resolution.graph, 'parse_agtype', return_value=None
        ):
            result = await resolution.load_integration(db, 'integration-1')
        self.assertIsNone(result)


class LoadIntegrationOrgSlugTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify load_integration_org_slug resolves the owning org's slug."""

    async def test_returns_none_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await resolution.load_integration_org_slug(
            db, 'integration-1'
        )
        self.assertIsNone(result)

    async def test_returns_slug(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'slug': '"acme"'}]
        with mock.patch.object(
            resolution.graph, 'parse_agtype', return_value='acme'
        ):
            result = await resolution.load_integration_org_slug(
                db, 'integration-1'
            )
        self.assertEqual(result, 'acme')


class LoadPluginOptionsTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify load_plugin_options reads capabilities.identity.options."""

    async def test_returns_empty_when_integration_missing(self) -> None:
        with mock.patch.object(
            resolution,
            'load_integration',
            new=mock.AsyncMock(return_value=None),
        ):
            result = await resolution.load_plugin_options(
                mock.AsyncMock(), 'integration-1'
            )
        self.assertEqual(result, {})

    async def test_returns_identity_capability_options(self) -> None:
        integration = _integration()
        integration['capabilities'] = {
            'identity': {'enabled': True, 'options': {'a': 1}}
        }
        with mock.patch.object(
            resolution,
            'load_integration',
            new=mock.AsyncMock(return_value=integration),
        ):
            result = await resolution.load_plugin_options(
                mock.AsyncMock(), 'integration-1'
            )
        self.assertEqual(result, {'a': 1})
