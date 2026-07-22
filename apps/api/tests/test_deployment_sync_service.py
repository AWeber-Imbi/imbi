"""Tests for the deployment-sync service (run, status)."""

from __future__ import annotations

import unittest
from unittest import mock

import fastapi

from imbi.api.deployment_sync import service


class RunResyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_invokes_resync_for_project(self) -> None:
        db = mock.AsyncMock()
        summary = mock.Mock()
        resync = mock.AsyncMock(return_value=summary)
        with mock.patch(
            'imbi.api.endpoints.project_deployments.resync_for_project',
            resync,
        ):
            result = await service.run_resync(db, 'octo', 'p1', 25)
        self.assertIs(summary, result)
        kwargs = resync.await_args.kwargs
        self.assertEqual('octo', kwargs['org_slug'])
        self.assertEqual('p1', kwargs['project_id'])
        self.assertEqual(25, kwargs['limit'])
        # Synthetic service-account principal, no acting user.
        self.assertIsNone(kwargs['auth'].user)
        self.assertEqual(service.REQUESTED_BY, kwargs['auth'].principal_name)

    async def test_unsupported_plugin_raises_unavailable(self) -> None:
        db = mock.AsyncMock()
        with mock.patch(
            'imbi.api.endpoints.project_deployments.resync_for_project',
            mock.AsyncMock(
                side_effect=fastapi.HTTPException(
                    status_code=400, detail='does not support'
                )
            ),
        ):
            with self.assertRaises(service.DeploymentSyncUnavailable):
                await service.run_resync(db, 'octo', 'p1', 1)

    async def test_no_capability_raises_unavailable(self) -> None:
        db = mock.AsyncMock()
        with mock.patch(
            'imbi.api.endpoints.project_deployments.resync_for_project',
            mock.AsyncMock(
                side_effect=fastapi.HTTPException(
                    status_code=404, detail='no capability'
                )
            ),
        ):
            with self.assertRaises(service.DeploymentSyncUnavailable):
                await service.run_resync(db, 'octo', 'p1', 1)

    async def test_other_http_error_propagates(self) -> None:
        db = mock.AsyncMock()
        with mock.patch(
            'imbi.api.endpoints.project_deployments.resync_for_project',
            mock.AsyncMock(
                side_effect=fastapi.HTTPException(
                    status_code=503, detail='no credentials'
                )
            ),
        ):
            with self.assertRaises(fastapi.HTTPException):
                await service.run_resync(db, 'octo', 'p1', 1)


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_status_writes_all_fields(self) -> None:
        db = mock.AsyncMock()
        summary = mock.Mock()
        summary.observed = 7
        summary.releases_created = 2
        summary.releases_updated = 1
        summary.events_recorded = 5
        summary.errors = [mock.Mock()]
        await service.set_status(
            db,
            'p1',
            status='success',
            requested_by='alice',
            summary=summary,
        )
        db.execute.assert_awaited_once()
        params = db.execute.await_args.args[1]
        self.assertEqual('success', params['status'])
        self.assertEqual(7, params['observed'])
        self.assertEqual(2, params['releases_created'])
        self.assertEqual(1, params['releases_updated'])
        self.assertEqual(5, params['events'])
        self.assertEqual(1, params['errors'])
        self.assertEqual('alice', params['by'])

    async def test_set_status_unguarded_omits_where(self) -> None:
        db = mock.AsyncMock()
        await service.set_status(db, 'p1', status='running')
        query = db.execute.await_args.args[0]
        self.assertNotIn('WHERE', query)

    async def test_set_status_guard_adds_timestamp_predicate(self) -> None:
        db = mock.AsyncMock()
        enqueued_at = service.now_iso()
        await service.set_status(
            db,
            'p1',
            status='queued',
            retry=False,
            only_if_before=enqueued_at,
        )
        db.execute.assert_awaited_once()
        query = db.execute.await_args.args[0]
        # The guard must land between MATCH and SET so a status that
        # already advanced past the enqueue time is left untouched.
        self.assertIn('WHERE p.deployment_sync_at IS NULL', query)
        self.assertIn('p.deployment_sync_at < {only_if_before}', query)
        self.assertLess(query.index('WHERE'), query.index('SET'))
        params = db.execute.await_args.args[1]
        self.assertEqual(enqueued_at, params['only_if_before'])

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
                'observed': None,
                'releases_created': None,
                'releases_updated': None,
                'events': None,
                'errors': None,
                'error': None,
            }
        ]
        status = await service.read_status(db, 'p1')
        self.assertEqual('idle', status.status)
        self.assertIsNone(status.last_synced_at)
        self.assertIsNone(status.observed)

    async def test_read_status_parses_success(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'status': '"success"',
                'at': '"2026-07-20T12:00:00+00:00"',
                'requested_by': '"alice"',
                'observed': 12,
                'releases_created': 3,
                'releases_updated': 2,
                'events': 9,
                'errors': 0,
                'error': '""',
            }
        ]
        status = await service.read_status(db, 'p1')
        self.assertEqual('success', status.status)
        self.assertEqual(12, status.observed)
        self.assertEqual(3, status.releases_created)
        self.assertEqual(2, status.releases_updated)
        self.assertEqual(9, status.events_recorded)
        self.assertEqual(0, status.errors)
        self.assertEqual('alice', status.requested_by)
        self.assertIsNotNone(status.last_synced_at)
        self.assertIsNone(status.error)
