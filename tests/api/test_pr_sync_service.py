"""Tests for the PR-sync service (resolution, status, run)."""

from __future__ import annotations

import unittest
from unittest import mock

import fastapi
from imbi_common.plugins.base import PullRequestSyncCapability

from imbi_api.pr_sync import service


class _FakePRSync(PullRequestSyncCapability):
    async def check_available(self, *, ctx, credentials) -> bool:  # type: ignore[no-untyped-def]
        return True

    async def sync_all_history(self, *, ctx, credentials):  # type: ignore[no-untyped-def]
        return 7


class _UnavailablePRSync(PullRequestSyncCapability):
    async def check_available(self, *, ctx, credentials) -> bool:  # type: ignore[no-untyped-def]
        return False

    async def sync_all_history(self, *, ctx, credentials):  # type: ignore[no-untyped-def]
        return 0


def _resolved(handler_cls: type) -> mock.Mock:
    return mock.Mock(capability_cls=handler_cls, encrypted_credentials={})


class RunSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_invokes_handler_sync_all_history(self) -> None:
        db = mock.AsyncMock()
        with (
            mock.patch.object(
                service,
                'resolve_capability',
                mock.AsyncMock(return_value=_resolved(_FakePRSync)),
            ),
            mock.patch.object(
                service,
                '_build_context',
                mock.AsyncMock(return_value=mock.Mock()),
            ),
        ):
            result = await service.run_sync(db, 'octo', 'p1')
        self.assertEqual(7, result)

    async def test_unresolved_raises_unavailable(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            service,
            'resolve_capability',
            mock.AsyncMock(
                side_effect=fastapi.HTTPException(
                    status_code=404, detail='no capability'
                )
            ),
        ):
            with self.assertRaises(service.PRSyncUnavailable):
                await service.run_sync(db, 'octo', 'p1')


class CheckAvailableTests(unittest.IsolatedAsyncioTestCase):
    async def test_available_does_not_raise(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            service,
            '_build_context',
            mock.AsyncMock(return_value=mock.Mock()),
        ):
            await service.check_available(
                db, 'octo', 'p1', _resolved(_FakePRSync)
            )

    async def test_unavailable_raises(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            service,
            '_build_context',
            mock.AsyncMock(return_value=mock.Mock()),
        ):
            with self.assertRaises(service.PRSyncUnavailable):
                await service.check_available(
                    db, 'octo', 'p1', _resolved(_UnavailablePRSync)
                )


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_status_writes_all_fields(self) -> None:
        db = mock.AsyncMock()
        await service.set_status(
            db,
            'p1',
            status='success',
            requested_by='alice',
            prs=7,
        )
        db.execute.assert_awaited_once()
        params = db.execute.await_args.args[1]
        self.assertEqual('success', params['status'])
        self.assertEqual(7, params['prs'])
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
                'prs': None,
                'error': None,
            }
        ]
        status = await service.read_status(db, 'p1')
        self.assertEqual('idle', status.status)
        self.assertIsNone(status.last_synced_at)
        self.assertIsNone(status.prs_synced)

    async def test_read_status_parses_success(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'status': '"success"',
                'at': '"2026-06-04T12:00:00+00:00"',
                'requested_by': '"alice"',
                'prs': 12,
                'error': '""',
            }
        ]
        status = await service.read_status(db, 'p1')
        self.assertEqual('success', status.status)
        self.assertEqual(12, status.prs_synced)
        self.assertEqual('alice', status.requested_by)
        self.assertIsNotNone(status.last_synced_at)
        self.assertIsNone(status.error)

    async def test_read_status_no_rows_returns_idle(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        status = await service.read_status(db, 'p1')
        self.assertEqual('idle', status.status)
