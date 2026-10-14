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
