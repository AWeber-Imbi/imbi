"""Tests for identity-flow operations."""

import contextlib
import datetime
import typing
import unittest
from unittest import mock

from imbi_common.plugins.base import IdentityCredentials, IdentityProfile
from imbi_common.plugins.errors import PluginNotFoundError

from imbi_api.identity import errors, flows


def _patch_load_handler(
    handler: object,
    creds: dict[str, str] | None = None,
) -> contextlib.AbstractContextManager[typing.Any]:
    """Common patch helper for ``flows._load_plugin_handler``."""
    entry = mock.MagicMock()
    entry.manifest = mock.MagicMock(slug='oidc', default_scopes=['openid'])
    return mock.patch.object(
        flows,
        '_load_plugin_handler',
        new=mock.AsyncMock(return_value=(entry, handler, creds or {})),
    )


class LoadPluginHandlerTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify _load_plugin_handler resolves plugin -> registered handler."""

    async def test_raises_plugin_not_found_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        with self.assertRaises(PluginNotFoundError):
            await flows._load_plugin_handler(db, 'plugin-1')

    async def test_raises_plugin_not_found_when_handler_wrong_type(
        self,
    ) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'slug': '"oidc"'}]
        non_identity = mock.MagicMock()
        entry = mock.MagicMock()
        entry.handler_cls = mock.MagicMock(return_value=non_identity)
        with (
            mock.patch.object(
                flows.graph, 'parse_agtype', return_value='oidc'
            ),
            mock.patch.object(flows, 'get_plugin', return_value=entry),
        ):
            with self.assertRaises(PluginNotFoundError):
                await flows._load_plugin_handler(db, 'plugin-1')

    async def test_returns_entry_handler_creds(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'slug': '"oidc"'}]
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        entry = mock.MagicMock()
        entry.handler_cls = mock.MagicMock(return_value=handler)
        with (
            mock.patch.object(
                flows.graph, 'parse_agtype', return_value='oidc'
            ),
            mock.patch.object(flows, 'get_plugin', return_value=entry),
            mock.patch.object(
                flows.plugin_credentials,
                'get_plugin_credentials',
                new=mock.AsyncMock(return_value={'client_id': 'cid'}),
            ),
        ):
            result = await flows._load_plugin_handler(db, 'plugin-1')
        self.assertEqual(result[0], entry)
        self.assertEqual(result[1], handler)
        self.assertEqual(result[2], {'client_id': 'cid'})


class StartFlowTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify start_flow returns auth URL + state token."""

    async def test_returns_authorization_url_and_state_token(self) -> None:
        db = mock.AsyncMock()
        request = mock.MagicMock()
        request.authorization_url = 'https://idp/authorize?...'
        request.code_verifier = 'pkce-verifier'
        request.polling = None
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.authorization_request = mock.AsyncMock(return_value=request)
        with (
            _patch_load_handler(handler),
            mock.patch.object(
                flows.state,
                'encode_identity_state',
                return_value='state-token',
            ),
        ):
            url, state_token, polling = await flows.start_flow(
                db,
                plugin_id='plugin-1',
                redirect_uri='https://imbi/cb',
                actor_user_id='user-1',
            )
        self.assertEqual(url, 'https://idp/authorize?...')
        self.assertEqual(state_token, 'state-token')
        self.assertIsNone(polling)


class CompleteFlowTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify complete_flow persists the connection on success."""

    async def test_persists_connection_when_actor_present(self) -> None:
        db = mock.AsyncMock()
        state_data = mock.MagicMock()
        state_data.plugin_id = 'plugin-1'
        state_data.actor_user_id = 'user-1'
        state_data.redirect_uri = 'https://imbi/cb'
        state_data.code_verifier = 'verifier'
        state_data.return_to = '/projects'

        profile = IdentityProfile(subject='sub')
        credentials = IdentityCredentials(access_token='at')
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.exchange_code = mock.AsyncMock(
            return_value=(profile, credentials)
        )

        with (
            mock.patch.object(
                flows.state,
                'decode_identity_state',
                return_value=state_data,
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'upsert_connection',
                new=mock.AsyncMock(return_value='conn-1'),
            ) as upsert,
        ):
            result = await flows.complete_flow(
                db, code='auth-code', state_token='state-token'
            )
        upsert.assert_awaited_once()
        self.assertEqual(result[0], profile)
        self.assertEqual(result[1], credentials)
        self.assertEqual(result[2], 'plugin-1')
        self.assertEqual(result[3], '/projects')

    async def test_skips_persist_when_no_actor(self) -> None:
        db = mock.AsyncMock()
        state_data = mock.MagicMock()
        state_data.plugin_id = 'plugin-1'
        state_data.actor_user_id = None
        state_data.redirect_uri = 'https://imbi/cb'
        state_data.code_verifier = None
        state_data.return_to = None
        profile = IdentityProfile(subject='sub')
        credentials = IdentityCredentials(access_token='at')
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.exchange_code = mock.AsyncMock(
            return_value=(profile, credentials)
        )
        with (
            mock.patch.object(
                flows.state,
                'decode_identity_state',
                return_value=state_data,
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'upsert_connection',
                new=mock.AsyncMock(),
            ) as upsert,
        ):
            await flows.complete_flow(
                db, code='auth-code', state_token='state-token'
            )
        upsert.assert_not_called()

    async def test_raises_when_state_missing_plugin_id(self) -> None:
        db = mock.AsyncMock()
        state_data = mock.MagicMock()
        state_data.plugin_id = None
        with mock.patch.object(
            flows.state,
            'decode_identity_state',
            return_value=state_data,
        ):
            with self.assertRaises(ValueError):
                await flows.complete_flow(db, code='c', state_token='s')


class CompleteLoginFlowTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify complete_login_flow exchanges but does not persist."""

    async def test_does_not_upsert_connection(self) -> None:
        db = mock.AsyncMock()
        state_data = mock.MagicMock()
        state_data.plugin_id = 'plugin-1'
        state_data.redirect_uri = 'https://imbi/cb'
        state_data.code_verifier = 'verifier'
        state_data.return_to = '/dashboard'

        profile = IdentityProfile(subject='sub', email='u@x')
        credentials = IdentityCredentials(access_token='at')
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.exchange_code = mock.AsyncMock(
            return_value=(profile, credentials)
        )
        with (
            mock.patch.object(
                flows.state,
                'decode_login_state',
                return_value=state_data,
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'upsert_connection',
                new=mock.AsyncMock(),
            ) as upsert,
        ):
            (
                returned_profile,
                returned_creds,
                plugin_id,
                return_to,
            ) = await flows.complete_login_flow(db, code='c', state_token='s')
        upsert.assert_not_called()
        self.assertEqual(returned_profile, profile)
        self.assertEqual(returned_creds, credentials)
        self.assertEqual(plugin_id, 'plugin-1')
        self.assertEqual(return_to, '/dashboard')

    async def test_raises_when_state_missing_plugin_id(self) -> None:
        db = mock.AsyncMock()
        state_data = mock.MagicMock()
        state_data.plugin_id = None
        with mock.patch.object(
            flows.state,
            'decode_login_state',
            return_value=state_data,
        ):
            with self.assertRaises(ValueError):
                await flows.complete_login_flow(db, code='c', state_token='s')


class RefreshConnectionTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify refresh_connection's success / no-token / IdP-error paths."""

    async def test_raises_identity_required_when_no_connection(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            flows.repository,
            'load_connection',
            new=mock.AsyncMock(return_value=None),
        ):
            with self.assertRaises(errors.IdentityRequiredError):
                await flows.refresh_connection(
                    db, plugin_id='p', actor_user_id='u'
                )

    async def test_raises_refresh_failed_when_no_refresh_token(self) -> None:
        db = mock.AsyncMock()
        connection = mock.MagicMock()
        connection.refresh_token = None
        with mock.patch.object(
            flows.repository,
            'load_connection',
            new=mock.AsyncMock(return_value=connection),
        ):
            with self.assertRaises(errors.IdentityRefreshFailed):
                await flows.refresh_connection(
                    db, plugin_id='p', actor_user_id='u'
                )

    async def test_marks_expired_when_idp_refresh_raises(self) -> None:
        db = mock.AsyncMock()
        connection = mock.MagicMock()
        connection.refresh_token = 'rt'
        connection.connection_id = 'conn-1'
        connection.subject = 'sub'
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.refresh = mock.AsyncMock(side_effect=RuntimeError('idp boom'))
        with (
            mock.patch.object(
                flows.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'mark_status',
                new=mock.AsyncMock(),
            ) as mark,
        ):
            with self.assertRaises(errors.IdentityRefreshFailed):
                await flows.refresh_connection(
                    db, plugin_id='p', actor_user_id='u'
                )
        mark.assert_awaited_once_with(db, 'conn-1', 'expired')

    async def test_happy_path_upserts_new_credentials(self) -> None:
        db = mock.AsyncMock()
        connection = mock.MagicMock()
        connection.refresh_token = 'rt'
        connection.subject = 'sub'
        new_credentials = IdentityCredentials(
            access_token='new-at',
            refresh_token='new-rt',
            expires_at=datetime.datetime.now(datetime.UTC),
        )
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.refresh = mock.AsyncMock(return_value=new_credentials)
        with (
            mock.patch.object(
                flows.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'upsert_connection',
                new=mock.AsyncMock(return_value='conn-1'),
            ) as upsert,
        ):
            result = await flows.refresh_connection(
                db, plugin_id='p', actor_user_id='u'
            )
        self.assertEqual(result, new_credentials)
        upsert.assert_awaited_once()


class RevokeConnectionTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify revoke_connection still records revocation on IdP errors."""

    async def test_returns_silently_when_no_connection(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            flows.repository,
            'load_connection',
            new=mock.AsyncMock(return_value=None),
        ):
            await flows.revoke_connection(db, plugin_id='p', actor_user_id='u')

    async def test_revokes_locally_on_idp_failure(self) -> None:
        db = mock.AsyncMock()
        connection = mock.MagicMock()
        connection.access_token = 'at'
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.revoke = mock.AsyncMock(side_effect=RuntimeError('idp boom'))
        with (
            mock.patch.object(
                flows.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'revoke',
                new=mock.AsyncMock(),
            ) as revoke,
        ):
            await flows.revoke_connection(db, plugin_id='p', actor_user_id='u')
        revoke.assert_awaited_once_with(db, 'p', 'u')

    async def test_happy_path_revokes_at_idp_and_locally(self) -> None:
        db = mock.AsyncMock()
        connection = mock.MagicMock()
        connection.access_token = 'at'
        handler = mock.MagicMock(spec=flows.IdentityPlugin)
        handler.revoke = mock.AsyncMock()
        with (
            mock.patch.object(
                flows.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            _patch_load_handler(handler),
            mock.patch.object(
                flows.repository,
                'revoke',
                new=mock.AsyncMock(),
            ) as revoke,
        ):
            await flows.revoke_connection(db, plugin_id='p', actor_user_id='u')
        handler.revoke.assert_awaited_once()
        revoke.assert_awaited_once_with(db, 'p', 'u')
