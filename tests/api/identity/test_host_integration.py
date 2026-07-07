"""Tests for the host-side identity hydration helper."""

import typing
import unittest
from unittest import mock

import fastapi
from imbi_common.plugins.base import (
    IdentityCredentials,
    PluginContext,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_api.identity import errors as identity_errors
from imbi_api.identity import host_integration


def _ctx() -> PluginContext:
    return PluginContext(
        project_id='p-1',
        project_slug='proj',
        org_slug='org',
        assignment_options={'k': 'v'},
    )


def _resolved(identity_integration_id: str | None) -> mock.MagicMock:
    resolved = mock.MagicMock()
    resolved.identity_integration_id = identity_integration_id
    return resolved


def _auth(user_id: str | None) -> mock.MagicMock:
    user = mock.MagicMock()
    user.id = user_id
    auth = mock.MagicMock()
    auth.user = user if user_id else None
    return auth


class AttachIdentityTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_no_identity_integration_only_stamps_actor(self) -> None:
        db = mock.AsyncMock()
        ctx = await host_integration.attach_identity(
            db, _ctx(), _resolved(None), _auth('user-1')
        )
        self.assertEqual(ctx.actor_user_id, 'user-1')
        self.assertIsNone(ctx.identity)

    async def test_no_user_leaves_actor_none(self) -> None:
        db = mock.AsyncMock()
        ctx = await host_integration.attach_identity(
            db, _ctx(), _resolved(None), _auth(None)
        )
        self.assertIsNone(ctx.actor_user_id)

    async def test_hydrates_identity_when_integration_id_set(self) -> None:
        db = mock.AsyncMock()
        hydrated = _ctx().model_copy(
            update={
                'actor_user_id': 'user-1',
                'identity': IdentityCredentials(access_token='at'),
            }
        )
        with mock.patch.object(
            host_integration.identity_resolution,
            'hydrate_identity',
            new=mock.AsyncMock(return_value=hydrated),
        ) as hydrate:
            ctx = await host_integration.attach_identity(
                db,
                _ctx(),
                _resolved('plug-1'),
                _auth('user-1'),
            )
        hydrate.assert_awaited_once()
        # Helper passes a stamped ctx, not the raw one.
        passed_ctx = hydrate.await_args.args[1]
        self.assertEqual(passed_ctx.actor_user_id, 'user-1')
        self.assertEqual(ctx.identity.access_token, 'at')

    async def test_identity_required_maps_to_401(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            host_integration.identity_resolution,
            'hydrate_identity',
            side_effect=identity_errors.IdentityRequiredError(
                integration_id='plug-1',
                start_url='/me/identities/plug-1/start',
            ),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx_mgr:
                await host_integration.attach_identity(
                    db,
                    _ctx(),
                    _resolved('plug-1'),
                    _auth('user-1'),
                )
        exc = ctx_mgr.exception
        self.assertEqual(exc.status_code, 401)
        self.assertEqual(
            exc.headers,
            {'WWW-Authenticate': 'Imbi-Identity integration_id=plug-1'},
        )
        self.assertIsInstance(exc.detail, dict)
        detail = typing.cast('dict[str, typing.Any]', exc.detail)
        self.assertEqual(detail['error'], 'identity_required')
        self.assertEqual(detail['integration_id'], 'plug-1')
        self.assertEqual(detail['start_url'], '/me/identities/plug-1/start')


class CallWithIdentityRetryTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify the retry-on-401 wrapper around plugin invocations."""

    async def test_returns_value_on_first_call(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx().model_copy(
            update={
                'actor_user_id': 'user-1',
                'identity': IdentityCredentials(access_token='at'),
            }
        )
        with mock.patch.object(
            host_integration,
            'attach_identity',
            new=mock.AsyncMock(return_value=ctx),
        ) as attach:
            fn = mock.AsyncMock(return_value='result')
            value = await host_integration.call_with_identity_retry(
                db, _ctx(), _resolved('plug-1'), _auth('user-1'), fn=fn
            )
        self.assertEqual(value, 'result')
        attach.assert_awaited_once()
        fn.assert_awaited_once_with(ctx)

    async def test_no_identity_integration_does_not_retry(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx().model_copy(update={'actor_user_id': 'user-1'})
        with mock.patch.object(
            host_integration,
            'attach_identity',
            new=mock.AsyncMock(return_value=ctx),
        ):
            fn = mock.AsyncMock(side_effect=PluginAuthenticationFailed('401'))
            with self.assertRaises(PluginAuthenticationFailed):
                await host_integration.call_with_identity_retry(
                    db, _ctx(), _resolved(None), _auth('user-1'), fn=fn
                )
        # Called exactly once, no retry.
        fn.assert_awaited_once()

    async def test_retries_after_refresh_on_401(self) -> None:
        db = mock.AsyncMock()
        first_ctx = _ctx().model_copy(
            update={
                'actor_user_id': 'user-1',
                'identity': IdentityCredentials(access_token='old'),
            }
        )
        second_ctx = _ctx().model_copy(
            update={
                'actor_user_id': 'user-1',
                'identity': IdentityCredentials(access_token='new'),
            }
        )
        from imbi_api.identity import flows

        attach = mock.AsyncMock(side_effect=[first_ctx, second_ctx])
        fn_call_count = {'n': 0}

        async def fn(ctx: PluginContext) -> str:
            fn_call_count['n'] += 1
            if fn_call_count['n'] == 1:
                raise PluginAuthenticationFailed('401')
            return f'ok:{ctx.identity.access_token}'

        with (
            mock.patch.object(host_integration, 'attach_identity', attach),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(return_value=mock.MagicMock()),
            ) as refresh,
        ):
            value = await host_integration.call_with_identity_retry(
                db, _ctx(), _resolved('plug-1'), _auth('user-1'), fn=fn
            )
        self.assertEqual(value, 'ok:new')
        refresh.assert_awaited_once()
        self.assertEqual(attach.await_count, 2)
        self.assertEqual(fn_call_count['n'], 2)

    async def test_refresh_failure_maps_to_401(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx().model_copy(
            update={
                'actor_user_id': 'user-1',
                'identity': IdentityCredentials(access_token='old'),
            }
        )
        from imbi_api.identity import flows

        with (
            mock.patch.object(
                host_integration,
                'attach_identity',
                new=mock.AsyncMock(return_value=ctx),
            ),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(
                    side_effect=identity_errors.IdentityRefreshFailed('nope')
                ),
            ),
        ):
            fn = mock.AsyncMock(side_effect=PluginAuthenticationFailed('401'))
            with self.assertRaises(fastapi.HTTPException) as cm:
                await host_integration.call_with_identity_retry(
                    db, _ctx(), _resolved('plug-1'), _auth('user-1'), fn=fn
                )
        self.assertEqual(cm.exception.status_code, 401)
        detail = typing.cast('dict[str, typing.Any]', cm.exception.detail)
        self.assertEqual(detail['error'], 'identity_required')
        self.assertEqual(detail['integration_id'], 'plug-1')

    async def test_second_401_propagates(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx().model_copy(
            update={
                'actor_user_id': 'user-1',
                'identity': IdentityCredentials(access_token='at'),
            }
        )
        from imbi_api.identity import flows

        with (
            mock.patch.object(
                host_integration,
                'attach_identity',
                new=mock.AsyncMock(return_value=ctx),
            ),
            mock.patch.object(
                flows,
                'refresh_connection',
                new=mock.AsyncMock(return_value=mock.MagicMock()),
            ),
        ):
            fn = mock.AsyncMock(side_effect=PluginAuthenticationFailed('401'))
            with self.assertRaises(PluginAuthenticationFailed):
                await host_integration.call_with_identity_retry(
                    db, _ctx(), _resolved('plug-1'), _auth('user-1'), fn=fn
                )
        self.assertEqual(fn.await_count, 2)
