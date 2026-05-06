"""Tests for the host-side identity hydration helper."""

import typing
import unittest
from unittest import mock

import fastapi
from imbi_common.plugins.base import (
    IdentityCredentials,
    PluginContext,
)

from imbi_api.identity import errors as identity_errors
from imbi_api.identity import host_integration


def _ctx() -> PluginContext:
    return PluginContext(
        project_id='p-1',
        project_slug='proj',
        org_slug='org',
        assignment_options={'k': 'v'},
    )


def _resolved(identity_plugin_id: str | None) -> mock.MagicMock:
    resolved = mock.MagicMock()
    resolved.identity_plugin_id = identity_plugin_id
    return resolved


def _auth(user_id: str | None) -> mock.MagicMock:
    user = mock.MagicMock()
    user.id = user_id
    auth = mock.MagicMock()
    auth.user = user if user_id else None
    return auth


class AttachIdentityTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_no_identity_plugin_only_stamps_actor(self) -> None:
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

    async def test_hydrates_identity_when_plugin_id_set(self) -> None:
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
                plugin_id='plug-1',
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
            {'WWW-Authenticate': 'Imbi-Identity plugin_id=plug-1'},
        )
        self.assertIsInstance(exc.detail, dict)
        detail = typing.cast('dict[str, typing.Any]', exc.detail)
        self.assertEqual(detail['error'], 'identity_required')
        self.assertEqual(detail['plugin_id'], 'plug-1')
        self.assertEqual(detail['start_url'], '/me/identities/plug-1/start')
