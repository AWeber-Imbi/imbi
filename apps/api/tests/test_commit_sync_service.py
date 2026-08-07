"""Tests for the commit-sync service (resolution, status, run)."""

from __future__ import annotations

import typing
import unittest
from unittest import mock

import fastapi

from imbi.api.commit_sync import service
from imbi.common.plugins.base import CommitSyncCapability


class _FakeCommitSync(CommitSyncCapability):
    async def check_available(self, *, ctx, credentials) -> bool:  # type: ignore[no-untyped-def]
        return True

    async def sync_all_history(self, *, ctx, credentials):  # type: ignore[no-untyped-def]
        return (5, 1)


class _TagCommitSync(CommitSyncCapability):
    """Implements the bounded per-tag sync and records what it got."""

    calls: typing.ClassVar[list[str]] = []

    async def sync_all_history(self, *, ctx, credentials):  # type: ignore[no-untyped-def]
        raise AssertionError('the bounded path must not backfill everything')

    async def sync_tag(self, *, ctx, credentials, tag):  # type: ignore[no-untyped-def]
        self.calls.append(tag)
        return 1


class _UnavailableCommitSync(CommitSyncCapability):
    async def check_available(self, *, ctx, credentials) -> bool:  # type: ignore[no-untyped-def]
        return False

    async def sync_all_history(self, *, ctx, credentials):  # type: ignore[no-untyped-def]
        return (0, 0)


def _resolved(handler_cls: type) -> mock.Mock:
    return mock.Mock(capability_cls=handler_cls, encrypted_credentials={})


class RunSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_invokes_handler_sync_all_history(self) -> None:
        db = mock.AsyncMock()
        with (
            mock.patch.object(
                service,
                'resolve_capability',
                mock.AsyncMock(return_value=_resolved(_FakeCommitSync)),
            ),
            mock.patch.object(
                service,
                '_build_context',
                mock.AsyncMock(return_value=mock.Mock()),
            ),
        ):
            result = await service.run_sync(db, 'octo', 'p1')
        self.assertEqual((5, 1), result)

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
            with self.assertRaises(service.CommitSyncUnavailable):
                await service.run_sync(db, 'octo', 'p1')


class RunTagSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _TagCommitSync.calls.clear()

    def _patch(self, handler_cls: type) -> typing.Any:
        return (
            mock.patch.object(
                service,
                'resolve_capability',
                mock.AsyncMock(return_value=_resolved(handler_cls)),
            ),
            mock.patch.object(
                service,
                '_build_context',
                mock.AsyncMock(return_value=mock.Mock()),
            ),
        )

    async def test_invokes_handler_sync_tag(self) -> None:
        db = mock.AsyncMock()
        resolve, context = self._patch(_TagCommitSync)
        with resolve, context:
            written = await service.run_tag_sync(db, 'octo', 'p1', '1.2.3')
        self.assertEqual(1, written)
        self.assertEqual(['1.2.3'], _TagCommitSync.calls)

    async def test_unimplemented_propagates(self) -> None:
        """The default raises so the caller can fall back to a backfill."""
        db = mock.AsyncMock()
        resolve, context = self._patch(_FakeCommitSync)
        with resolve, context, self.assertRaises(NotImplementedError):
            await service.run_tag_sync(db, 'octo', 'p1', '1.2.3')

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
            with self.assertRaises(service.CommitSyncUnavailable):
                await service.run_tag_sync(db, 'octo', 'p1', '1.2.3')


class CheckAvailableTests(unittest.IsolatedAsyncioTestCase):
    async def test_available_does_not_raise(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            service,
            '_build_context',
            mock.AsyncMock(return_value=mock.Mock()),
        ):
            await service.check_available(
                db, 'octo', 'p1', _resolved(_FakeCommitSync)
            )

    async def test_unavailable_raises(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            service,
            '_build_context',
            mock.AsyncMock(return_value=mock.Mock()),
        ):
            with self.assertRaises(service.CommitSyncUnavailable):
                await service.check_available(
                    db, 'octo', 'p1', _resolved(_UnavailableCommitSync)
                )


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
