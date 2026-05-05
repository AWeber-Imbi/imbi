"""Tests for the identity refresh sweeper."""

import asyncio
import unittest
from unittest import mock

from imbi_api.identity import errors, sweeper


class LockKeyTestCase(unittest.TestCase):
    """Verify the Valkey lock key encodes plugin + user."""

    def test_lock_key_format(self) -> None:
        self.assertEqual(
            sweeper._lock_key('plugin-1', 'user-9'),
            'imbi:identity:refresh:plugin-1:user-9',
        )


class TryLockTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify _try_lock translates Valkey results to booleans."""

    async def test_returns_true_on_set_success(self) -> None:
        client = mock.AsyncMock()
        client.set.return_value = True
        self.assertTrue(await sweeper._try_lock(client, 'k'))
        client.set.assert_awaited_once_with(
            'k', '1', nx=True, ex=sweeper.LOCK_TTL_SECONDS
        )

    async def test_returns_false_when_set_returns_none(self) -> None:
        client = mock.AsyncMock()
        client.set.return_value = None
        self.assertFalse(await sweeper._try_lock(client, 'k'))

    async def test_returns_false_on_exception(self) -> None:
        client = mock.AsyncMock()
        client.set.side_effect = RuntimeError('valkey down')
        self.assertFalse(await sweeper._try_lock(client, 'k'))


class RefreshOneTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify _refresh_one's lock + flow + expired-marking branches."""

    def setUp(self) -> None:
        self.db = mock.AsyncMock()
        self.client = mock.AsyncMock()

    async def test_skips_when_plugin_id_missing(self) -> None:
        with mock.patch.object(sweeper, '_try_lock') as try_lock:
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': '', 'user_id': 'u'}
            )
        try_lock.assert_not_called()

    async def test_skips_when_user_id_missing(self) -> None:
        with mock.patch.object(sweeper, '_try_lock') as try_lock:
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': ''}
            )
        try_lock.assert_not_called()

    async def test_skips_when_lock_not_acquired(self) -> None:
        with (
            mock.patch.object(
                sweeper,
                '_try_lock',
                new=mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(sweeper.flows, 'refresh_connection') as refresh,
        ):
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': 'u'}
            )
        refresh.assert_not_called()

    async def test_happy_path_invokes_refresh(self) -> None:
        with (
            mock.patch.object(
                sweeper,
                '_try_lock',
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                sweeper.flows,
                'refresh_connection',
                new=mock.AsyncMock(),
            ) as refresh,
        ):
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': 'u'}
            )
        refresh.assert_awaited_once()

    async def test_refresh_failed_marks_expired(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'active'
        connection.connection_id = 'conn-1'
        with (
            mock.patch.object(
                sweeper,
                '_try_lock',
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                sweeper.flows,
                'refresh_connection',
                new=mock.AsyncMock(
                    side_effect=errors.IdentityRefreshFailed('expired')
                ),
            ),
            mock.patch.object(
                sweeper.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                sweeper.repository,
                'mark_status',
                new=mock.AsyncMock(),
            ) as mark,
        ):
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': 'u'}
            )
        mark.assert_awaited_once_with(self.db, 'conn-1', 'expired')

    async def test_refresh_failed_already_expired_skips_mark(self) -> None:
        connection = mock.MagicMock()
        connection.status = 'expired'
        with (
            mock.patch.object(
                sweeper,
                '_try_lock',
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                sweeper.flows,
                'refresh_connection',
                new=mock.AsyncMock(
                    side_effect=errors.IdentityRefreshFailed('x')
                ),
            ),
            mock.patch.object(
                sweeper.repository,
                'load_connection',
                new=mock.AsyncMock(return_value=connection),
            ),
            mock.patch.object(
                sweeper.repository,
                'mark_status',
                new=mock.AsyncMock(),
            ) as mark,
        ):
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': 'u'}
            )
        mark.assert_not_called()

    async def test_refresh_failed_load_error_does_not_propagate(self) -> None:
        # Regression for the CodeRabbit-flagged path: a graph error during
        # load_connection inside the IdentityRefreshFailed handler must
        # not bubble out of _refresh_one.
        with (
            mock.patch.object(
                sweeper,
                '_try_lock',
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                sweeper.flows,
                'refresh_connection',
                new=mock.AsyncMock(
                    side_effect=errors.IdentityRefreshFailed('x')
                ),
            ),
            mock.patch.object(
                sweeper.repository,
                'load_connection',
                new=mock.AsyncMock(side_effect=RuntimeError('graph down')),
            ),
            mock.patch.object(sweeper.repository, 'mark_status') as mark,
        ):
            # Should NOT raise.
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': 'u'}
            )
        mark.assert_not_called()

    async def test_unexpected_exception_swallowed(self) -> None:
        with (
            mock.patch.object(
                sweeper,
                '_try_lock',
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                sweeper.flows,
                'refresh_connection',
                new=mock.AsyncMock(side_effect=RuntimeError('boom')),
            ),
        ):
            # Should NOT raise.
            await sweeper._refresh_one(
                self.db, self.client, {'plugin_id': 'p', 'user_id': 'u'}
            )


class RunSweeperTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify the sweeper main loop honors the stop event."""

    async def test_stop_event_terminates_loop(self) -> None:
        db = mock.AsyncMock()
        client = mock.AsyncMock()
        stop = asyncio.Event()
        stop.set()  # already set — loop should not iterate.

        with mock.patch.object(
            sweeper.repository,
            'stale_connections',
            new=mock.AsyncMock(return_value=[]),
        ) as stale:
            await sweeper.run_sweeper(db, client, stop=stop)
        stale.assert_not_called()

    async def test_iteration_failure_logged_and_loop_continues(
        self,
    ) -> None:
        db = mock.AsyncMock()
        client = mock.AsyncMock()
        stop = asyncio.Event()

        # First call raises; second call (after the wait_for) sees
        # stop.set() and exits.
        async def stale_then_stop(_db: object, _horizon: object) -> list:
            stop.set()
            raise RuntimeError('graph down')

        with mock.patch.object(
            sweeper.repository,
            'stale_connections',
            new=mock.AsyncMock(side_effect=stale_then_stop),
        ):
            await sweeper.run_sweeper(db, client, stop=stop)

    async def test_processes_rows_then_stops(self) -> None:
        db = mock.AsyncMock()
        client = mock.AsyncMock()
        stop = asyncio.Event()

        rows = [{'plugin_id': 'p', 'user_id': 'u'}]

        async def stale(_db: object, _horizon: object) -> list:
            return rows

        async def refresh_then_stop(*_args: object, **_kwargs: object) -> None:
            stop.set()

        with (
            mock.patch.object(
                sweeper.repository,
                'stale_connections',
                new=mock.AsyncMock(side_effect=stale),
            ),
            mock.patch.object(
                sweeper,
                '_refresh_one',
                new=mock.AsyncMock(side_effect=refresh_then_stop),
            ) as refresh_one,
        ):
            await sweeper.run_sweeper(db, client, stop=stop)
        refresh_one.assert_awaited_once()
