"""Tests for the SonarQube lifecycle capability."""

import unittest
from unittest import mock

import httpx
import respx

from imbi.common.plugins.base import PluginContext, ServiceConnection
from imbi.plugins.sonarqube.lifecycle import SonarQubeLifecycle

_SLUG = 'sonarqube'
_URL = 'https://sonarqube.example.com'
_KEY = 'platform:demo'
_CREDS = {'api_token': 't'}
_DELETE = f'{_URL}/api/projects/delete'


def _ctx(
    *,
    integration_slug: str | None = _SLUG,
    identifier: str | None = None,
    options: dict[str, object] | None = None,
    team_slug: str | None = 'platform',
    holder: str | None = None,
    resolver: bool = True,
) -> PluginContext:
    connections = (
        [
            ServiceConnection(
                integration_slug=_SLUG,
                identifier=identifier,
                canonical_url=None,
            )
        ]
        if identifier
        else []
    )
    return PluginContext(
        project_id='p',
        project_slug='demo',
        org_slug='org',
        team_slug=team_slug,
        integration_slug=integration_slug,
        integration_options=options
        if options is not None
        else {'service_url': _URL},
        service_connections=connections,
        project_links={'sonarqube': f'{_URL}/dashboard?id=platform%3Ademo'},
        resolve_identifier_holder=(
            mock.AsyncMock(return_value=holder) if resolver else None
        ),
    )


class DeleteTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_deleted_removes_project_and_edge(self) -> None:
        route = respx.post(_DELETE).mock(return_value=httpx.Response(204))
        ctx = _ctx(identifier=_KEY)
        result = await SonarQubeLifecycle().on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertIn(_KEY, result.message or '')
        request = route.calls.last.request
        self.assertEqual(
            'application/x-www-form-urlencoded',
            request.headers['content-type'],
        )
        self.assertEqual(b'project=platform%3Ademo', request.read())
        assert ctx.service_writeback is not None
        self.assertTrue(ctx.service_writeback.remove)
        self.assertEqual(ctx.service_writeback.identifier, _KEY)
        self.assertEqual(
            ['sonarqube'], list(ctx.service_writeback.dashboard_links)
        )

    @respx.mock
    async def test_archived_deletes_too(self) -> None:
        route = respx.post(_DELETE).mock(return_value=httpx.Response(204))
        ctx = _ctx(identifier=_KEY)
        result = await SonarQubeLifecycle().on_project_archived(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertTrue(route.called)
        assert ctx.service_writeback is not None
        self.assertTrue(ctx.service_writeback.remove)

    @respx.mock
    async def test_already_gone_is_skipped_and_edge_removed(self) -> None:
        respx.post(_DELETE).mock(
            return_value=httpx.Response(
                404, json={'errors': [{'msg': 'not found'}]}
            )
        )
        ctx = _ctx(identifier=_KEY)
        result = await SonarQubeLifecycle().on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('does not exist', result.message or '')
        assert ctx.service_writeback is not None
        self.assertTrue(ctx.service_writeback.remove)

    @respx.mock
    async def test_refused_is_failed_and_edge_kept(self) -> None:
        respx.post(_DELETE).mock(return_value=httpx.Response(403))
        ctx = _ctx(identifier=_KEY)
        result = await SonarQubeLifecycle().on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'failed')
        self.assertIn('403', result.message or '')
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_foreign_key_is_not_deleted(self) -> None:
        # No Imbi project holds the key, but it is not this project's.
        route = respx.post(_DELETE)
        ctx = _ctx(identifier='other-team:billing')
        with self.assertLogs('imbi.plugins.sonarqube.lifecycle', 'WARNING'):
            result = await SonarQubeLifecycle().on_project_archived(
                ctx, _CREDS
            )
        self.assertEqual(result.status, 'skipped')
        self.assertIn(_KEY, result.message or '')
        self.assertFalse(route.called)
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_key_another_project_links_is_not_deleted(self) -> None:
        route = respx.post(_DELETE)
        ctx = _ctx(identifier=_KEY, holder='other-team-project')
        result = await SonarQubeLifecycle().on_project_archived(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('other-team-project', result.message or '')
        self.assertFalse(route.called)
        self.assertIsNone(ctx.service_writeback)
        lookup = ctx.resolve_identifier_holder
        assert isinstance(lookup, mock.AsyncMock)
        lookup.assert_awaited_once_with(_KEY)

    @respx.mock
    async def test_without_holder_resolver_is_not_deleted(self) -> None:
        route = respx.post(_DELETE)
        ctx = _ctx(identifier=_KEY, resolver=False)
        result = await SonarQubeLifecycle().on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertFalse(route.called)
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_transport_error_is_failed(self) -> None:
        respx.post(_DELETE).mock(side_effect=httpx.ConnectError('refused'))
        result = await SonarQubeLifecycle().on_project_archived(
            _ctx(identifier=_KEY), _CREDS
        )
        self.assertEqual(result.status, 'failed')


class UnconfiguredTestCase(unittest.IsolatedAsyncioTestCase):
    """Nothing to delete is ``skipped``, never ``failed``."""

    async def _assert_skipped(self, ctx: PluginContext, creds: dict) -> str:
        with respx.mock:
            route = respx.post(_DELETE)
            result = await SonarQubeLifecycle().on_project_deleted(ctx, creds)
            self.assertFalse(route.called)
        self.assertEqual(result.status, 'skipped')
        return result.message or ''

    async def test_without_integration_binding(self) -> None:
        message = await self._assert_skipped(
            _ctx(integration_slug=None), _CREDS
        )
        self.assertIn('not bound', message)

    async def test_without_service_url(self) -> None:
        message = await self._assert_skipped(_ctx(options={}), _CREDS)
        self.assertIn('service_url', message)

    async def test_without_token(self) -> None:
        message = await self._assert_skipped(_ctx(), {})
        self.assertIn('api_token', message)

    async def test_without_edge_or_team(self) -> None:
        message = await self._assert_skipped(_ctx(team_slug=None), _CREDS)
        self.assertIn('EXISTS_IN edge', message)

    async def test_without_edge_never_derives_a_key(self) -> None:
        # The doctor would guess ``platform:demo`` here; a delete must not.
        message = await self._assert_skipped(_ctx(), _CREDS)
        self.assertIn('no EXISTS_IN edge', message)
        self.assertIn('nothing to delete', message)

    async def test_edge_without_identifier_is_skipped(self) -> None:
        message = await self._assert_skipped(_ctx(identifier=''), _CREDS)
        self.assertIn('nothing to delete', message)


class OtherHooksTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_unarchive_is_not_implemented(self) -> None:
        with self.assertRaises(NotImplementedError):
            await SonarQubeLifecycle().on_project_unarchived(_ctx(), _CREDS)

    async def test_create_is_not_implemented(self) -> None:
        with self.assertRaises(NotImplementedError):
            await SonarQubeLifecycle().on_project_created(_ctx(), _CREDS)
