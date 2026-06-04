"""Tests for the commit-sync service (resolution, status, run)."""

from __future__ import annotations

import unittest
from unittest import mock

from imbi_common.plugins.base import ServicePlugin

from imbi_api.commit_sync import service


def _resolve_rows() -> list[dict[str, object]]:
    return [
        {
            'plugin_id': '"plg-1"',
            'tps_slug': '"github"',
            'api_endpoint': '"https://api.github.com"',
            'siblings': (
                '[{"slug": "github-commit-sync", "options": {}}, '
                '{"slug": "github-deployment", "options": {}}]'
            ),
        }
    ]


class ResolvePluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_plugin_and_siblings(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = _resolve_rows()
        with mock.patch.object(
            service, 'get_plugin', return_value=mock.Mock()
        ):
            resolved = await service._resolve_plugin(db, 'p1')
        self.assertEqual('plg-1', resolved.plugin_id)
        self.assertEqual('github', resolved.tps_slug)
        self.assertEqual('https://api.github.com', resolved.service_endpoint)
        slugs = {sp.slug for sp in resolved.service_plugins}
        self.assertEqual({'github-commit-sync', 'github-deployment'}, slugs)

    async def test_no_plugin_raises_unavailable(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        with self.assertRaises(service.CommitSyncUnavailable):
            await service._resolve_plugin(db, 'p1')


class RunSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_invokes_handler_sync_all_history(self) -> None:
        db = mock.AsyncMock()
        handler = mock.Mock()
        handler.sync_all_history = mock.AsyncMock(return_value=(5, 1))
        entry = mock.Mock()
        entry.handler_cls.return_value = handler
        resolved = service._ResolvedCommitSync(
            plugin_id='plg-1',
            entry=entry,
            tps_slug='github',
            service_endpoint='https://api.github.com',
            service_plugins=[ServicePlugin(slug='github')],
        )
        with (
            mock.patch.object(
                service,
                '_resolve_plugin',
                mock.AsyncMock(return_value=resolved),
            ),
            mock.patch.object(
                service,
                '_build_context',
                mock.AsyncMock(return_value=mock.Mock()),
            ),
            mock.patch.object(
                service,
                'get_plugin_credentials',
                mock.AsyncMock(return_value={'access_token': 'x'}),
            ),
        ):
            result = await service.run_sync(db, 'octo', 'p1')
        self.assertEqual((5, 1), result)
        handler.sync_all_history.assert_awaited_once()

    async def test_missing_method_raises_unavailable(self) -> None:
        db = mock.AsyncMock()
        handler = object()  # no sync_all_history
        entry = mock.Mock()
        entry.handler_cls.return_value = handler
        resolved = service._ResolvedCommitSync(
            plugin_id='plg-1',
            entry=entry,
            tps_slug='github',
            service_endpoint=None,
            service_plugins=[],
        )
        with (
            mock.patch.object(
                service,
                '_resolve_plugin',
                mock.AsyncMock(return_value=resolved),
            ),
            mock.patch.object(
                service,
                '_build_context',
                mock.AsyncMock(return_value=mock.Mock()),
            ),
            mock.patch.object(
                service,
                'get_plugin_credentials',
                mock.AsyncMock(return_value={}),
            ),
        ):
            with self.assertRaises(service.CommitSyncUnavailable):
                await service.run_sync(db, 'octo', 'p1')


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_status_writes_all_fields(self) -> None:
        db = mock.AsyncMock()
        await service.set_status(
            db,
            'p1',
            status='success',
            requested_by='alice',
            commits=7,
            tags=3,
        )
        db.execute.assert_awaited_once()
        params = db.execute.await_args.args[1]
        self.assertEqual('success', params['status'])
        self.assertEqual(7, params['commits'])
        self.assertEqual('alice', params['by'])

    async def test_set_status_retries_on_write_conflict(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = [
            Exception('Entity failed to be updated: 3'),
            [{'id': '"p1"'}],
        ]
        with mock.patch.object(service.asyncio, 'sleep'):
            await service.set_status(db, 'p1', status='running')
        self.assertEqual(2, db.execute.await_count)

    async def test_set_status_no_retry_drops_conflict(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = Exception('Entity failed to be updated: 3')
        await service.set_status(db, 'p1', status='queued', retry=False)
        db.execute.assert_awaited_once()

    async def test_set_status_swallows_unrelated_error(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = Exception('boom')
        await service.set_status(db, 'p1', status='running')
        db.execute.assert_awaited_once()

    async def test_read_status_idle_when_unset(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'status': None,
                'at': None,
                'requested_by': None,
                'commits': None,
                'tags': None,
                'error': None,
            }
        ]
        status = await service.read_status(db, 'p1')
        self.assertEqual('idle', status.status)
        self.assertIsNone(status.last_synced_at)
        self.assertIsNone(status.commits_synced)

    async def test_read_status_parses_success(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'status': '"success"',
                'at': '"2026-06-04T12:00:00+00:00"',
                'requested_by': '"alice"',
                'commits': 12,
                'tags': 4,
                'error': '""',
            }
        ]
        status = await service.read_status(db, 'p1')
        self.assertEqual('success', status.status)
        self.assertEqual(12, status.commits_synced)
        self.assertEqual(4, status.tags_synced)
        self.assertEqual('alice', status.requested_by)
        self.assertIsNotNone(status.last_synced_at)
        self.assertIsNone(status.error)
