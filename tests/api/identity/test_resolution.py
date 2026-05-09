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
            resolution._start_url_for('plugin-7'),
            '/me/identities/plugin-7/start',
        )


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
            await resolution.hydrate_identity(self.db, self.ctx, 'plugin-1')
        self.assertEqual(cm.exception.plugin_id, 'plugin-1')
        self.assertEqual(
            cm.exception.start_url, '/me/identities/plugin-1/start'
        )

    async def test_no_connection_raises_identity_required(self) -> None:
        with mock.patch.object(
            resolution.repository,
            'load_connection',
            new=mock.AsyncMock(return_value=None),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'plugin-1'
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
                    self.db, self.ctx, 'plugin-1'
                )

    async def test_missing_plugin_slug_raises_identity_required(self) -> None:
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
                '_plugin_slug',
                new=mock.AsyncMock(return_value=None),
            ),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'plugin-1'
                )

    async def test_plugin_not_found_raises_identity_required(self) -> None:
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
                '_plugin_slug',
                new=mock.AsyncMock(return_value='oidc'),
            ),
            mock.patch.object(
                resolution,
                'get_plugin',
                side_effect=PluginNotFoundError('oidc'),
            ),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'plugin-1'
                )

    async def test_handler_not_identity_plugin_raises(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.expires_at = None
        connection.refresh_token = None

        # Handler that is *not* an IdentityPlugin instance.
        non_identity_handler = mock.MagicMock()
        entry = mock.MagicMock()
        entry.handler_cls = mock.MagicMock(return_value=non_identity_handler)
        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                '_plugin_slug',
                new=mock.AsyncMock(return_value='oidc'),
            ),
            mock.patch.object(
                resolution,
                'get_plugin',
                return_value=entry,
            ),
        ):
            with self.assertRaises(identity_errors.IdentityRequiredError):
                await resolution.hydrate_identity(
                    self.db, self.ctx, 'plugin-1'
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
        handler = mock.MagicMock(spec=resolution.IdentityPlugin)
        handler.materialize = mock.AsyncMock(return_value=materialized)
        entry = mock.MagicMock()
        entry.handler_cls = mock.MagicMock(return_value=handler)

        # Patch the lazy import target inside imbi_api.identity.flows.
        from imbi_api.identity import flows

        with (
            mock.patch.object(resolution.repository, 'load_connection', load),
            mock.patch.object(
                resolution,
                '_plugin_slug',
                new=mock.AsyncMock(return_value='oidc'),
            ),
            mock.patch.object(
                resolution,
                'load_plugin_options',
                new=mock.AsyncMock(return_value={}),
            ),
            mock.patch.object(resolution, 'get_plugin', return_value=entry),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(return_value=mock.MagicMock()),
            ) as refresh_mock,
        ):
            await resolution.hydrate_identity(self.db, self.ctx, 'plugin-1')

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
        handler = mock.MagicMock(spec=resolution.IdentityPlugin)
        handler.materialize = mock.AsyncMock(return_value=materialized)
        entry = mock.MagicMock()
        entry.handler_cls = mock.MagicMock(return_value=handler)

        from imbi_api.identity import flows

        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                '_plugin_slug',
                new=mock.AsyncMock(return_value='oidc'),
            ),
            mock.patch.object(
                resolution,
                'load_plugin_options',
                new=mock.AsyncMock(return_value={}),
            ),
            mock.patch.object(resolution, 'get_plugin', return_value=entry),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(),
            ) as refresh_mock,
        ):
            await resolution.hydrate_identity(self.db, self.ctx, 'plugin-1')

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
                    self.db, self.ctx, 'plugin-1'
                )

    async def test_happy_path_calls_materialize(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.access_token = 'access'
        connection.refresh_token = 'refresh'
        connection.expires_at = None
        connection.scopes = ['email']

        materialized = mock.MagicMock(name='materialized')
        handler = mock.MagicMock(spec=resolution.IdentityPlugin)
        handler.materialize = mock.AsyncMock(return_value=materialized)
        entry = mock.MagicMock()
        entry.handler_cls = mock.MagicMock(return_value=handler)

        with (
            mock.patch.object(
                resolution.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                resolution,
                '_plugin_slug',
                new=mock.AsyncMock(return_value='oidc'),
            ),
            mock.patch.object(
                resolution,
                'load_plugin_options',
                new=mock.AsyncMock(return_value={'k': 'v'}),
            ),
            mock.patch.object(
                resolution,
                'get_plugin',
                return_value=entry,
            ),
        ):
            result = await resolution.hydrate_identity(
                self.db, self.ctx, 'plugin-1'
            )

        # ctx.model_copy is patched to capture the update kwargs.
        self.assertEqual(result, ('ctx-with', {'identity': materialized}))
        handler.materialize.assert_awaited_once()
        # The new identity_options + db kwargs are forwarded.
        _args, kwargs = handler.materialize.call_args
        self.assertEqual(kwargs.get('identity_options'), {'k': 'v'})
        self.assertIs(kwargs.get('db'), self.db)


class PluginSlugHelperTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify the private _plugin_slug helper."""

    async def test_returns_none_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        slug = await resolution._plugin_slug(db, 'plugin-1')
        self.assertIsNone(slug)

    async def test_parses_agtype_value(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'slug': '"oidc"'}]
        with mock.patch.object(
            resolution.graph,
            'parse_agtype',
            return_value='oidc',
        ):
            slug = await resolution._plugin_slug(db, 'plugin-1')
        self.assertEqual(slug, 'oidc')

    async def test_returns_none_when_parsed_value_is_none(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'slug': 'null'}]
        with mock.patch.object(
            resolution.graph,
            'parse_agtype',
            return_value=None,
        ):
            slug = await resolution._plugin_slug(db, 'plugin-1')
        self.assertIsNone(slug)
