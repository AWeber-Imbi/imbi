import unittest
from unittest import mock

from imbi.api.workflows import sweeper


class CancelOrphanAgentTasksTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_one_failing_task_does_not_stop_the_rest(self) -> None:
        store = mock.AsyncMock()
        store.orphan_agent_tasks.return_value = [
            {'organization_id': 'org', 'short_id': 'T-1'},
            {'organization_id': 'org', 'short_id': 'T-2'},
        ]
        tasks = mock.AsyncMock()
        tasks.set_control.side_effect = [RuntimeError('db down'), None]
        self.assertEqual(
            await sweeper.cancel_orphan_agent_tasks(store, tasks), 1
        )
        self.assertEqual(tasks.set_control.await_count, 2)


class RetryTaskTriggersTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_calls_trigger_for_recently_closed_tasks(self) -> None:
        """A run that the close hook failed to start is started by the
        sweep, and one failing task does not stop the rest."""
        store = mock.AsyncMock()
        store.orphan_agent_tasks.return_value = []
        store.unarchived.return_value = []
        tasks = mock.AsyncMock()
        tasks.closed_since.return_value = [{'id': 'a'}, {'id': 'b'}]
        trigger = mock.AsyncMock(side_effect=[RuntimeError('db down'), None])
        with mock.patch.object(
            sweeper, '_try_sweep_lock', mock.AsyncMock(return_value=True)
        ):
            await sweeper.sweep_once(store, tasks, trigger)
        tasks.closed_since.assert_awaited_once_with(
            sweeper.TASK_TRIGGER_WINDOW_SECONDS
        )
        self.assertEqual(
            trigger.await_args_list,
            [mock.call({'id': 'a'}), mock.call({'id': 'b'})],
        )
