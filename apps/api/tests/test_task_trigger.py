"""Tests for the ``task_completed`` workflow trigger.

These run against the live Postgres that ``root:services`` boots.
"""

import datetime
import typing
import unittest
import uuid

import pydantic

from apps.api.tests.endpoints.test_workflow_runs import HeldRunStore
from imbi.api import workflows
from imbi.api.workflows import task_trigger
from imbi.common.workflows.registry import task_completed


def _task(**changes: typing.Any) -> dict[str, typing.Any]:
    return {
        'id': uuid.uuid4(),
        'short_id': 'T-7',
        'agent_id': 'mender',
        'outcome': 'failed_external',
        'origin_kind': 'human',
        'origin': {'kind': 'human'},
        'chain_id': None,
        'closed_at': datetime.datetime.now(datetime.UTC),
        **changes,
    }


class FakeTasks:
    """Returns chain roots from a dict, as ``TaskStore.chain_root``."""

    def __init__(self) -> None:
        self.roots: dict[uuid.UUID, dict[str, typing.Any]] = {}

    async def chain_root(
        self, task: dict[str, typing.Any]
    ) -> dict[str, typing.Any] | None:
        chain_id = task['chain_id'] or task['id']
        return task if chain_id == task['id'] else self.roots.get(chain_id)


class ParamsTestCase(unittest.TestCase):
    def test_unknown_outcome_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            task_completed.Params.model_validate({'outcomes': ['done']})


class TaskTriggerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.org = f'wft-{suffix}'
        self.slug = f'wf-{suffix}'
        await workflows.initialize()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.addAsyncCleanup(self._cleanup)
        self.definitions = workflows.WorkflowStore(self.pool)
        await self.definitions.create(
            self.org,
            self.slug,
            workflows.Definition(
                name='Follow up',
                description='',
                owner_team_id='team',
                graph={'nodes': [], 'edges': []},
                settings={},
                validation={'issues': []},
                author='ops@example.com',
            ),
        )
        self.tasks = FakeTasks()
        self.trigger = task_trigger.TaskTrigger(
            self.definitions,
            HeldRunStore(self.pool),
            typing.cast(typing.Any, self.tasks),
        )

    async def _cleanup(self) -> None:
        async with self.pool.connection() as conn:
            for table in (
                'workflow_runtime.runs',
                'workflows.trigger_bindings',
                'workflows.workflows',
            ):
                await conn.execute(
                    f'DELETE FROM {table} WHERE organization_id = %s',
                    (self.org,),
                )
        await self.pool.close()

    async def _activate(self, **params: typing.Any) -> None:
        await self.definitions.activate(
            self.org,
            self.slug,
            1,
            'ops@example.com',
            [workflows.Trigger('done', 'task_completed', params)],
        )

    async def _runs(self) -> list[dict[str, typing.Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT trigger_node_id, origin_kind, origin_id, origin,'
                ' payload FROM workflow_runtime.runs'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            names = [c.name for c in cur.description or []]
            return [
                dict(zip(names, r, strict=True)) for r in await cur.fetchall()
            ]

    async def test_matching_task_starts_one_run(self) -> None:
        await self._activate(
            agent_id='mender', outcomes=['failed_external', 'failed_at_gate']
        )
        task = _task(organization_id=self.org)
        await self.trigger(task)
        await self.trigger(task)  # a repeat starts no second run
        self.assertEqual(
            await self._runs(),
            [
                {
                    'trigger_node_id': 'done',
                    'origin_kind': 'task_completed',
                    'origin_id': str(task['id']),
                    'origin': {
                        'kind': 'task_completed',
                        'task_id': 'T-7',
                        'depth': 1,
                    },
                    'payload': {
                        'task_id': 'T-7',
                        'agent_id': 'mender',
                        'outcome': 'failed_external',
                    },
                }
            ],
        )

    async def test_empty_filters_match_any_task(self) -> None:
        await self._activate()
        await self.trigger(
            _task(organization_id=self.org, agent_id='x', outcome='done_acted')
        )
        self.assertEqual(len(await self._runs()), 1)

    async def test_other_agent_or_outcome_starts_nothing(self) -> None:
        await self._activate(agent_id='mender', outcomes=['done_acted'])
        await self.trigger(_task(organization_id=self.org, agent_id='other'))
        await self.trigger(_task(organization_id=self.org))
        self.assertEqual(await self._runs(), [])

    async def test_task_closed_before_activation_starts_nothing(self) -> None:
        """The sweep calls the trigger again after the task closed; a
        workflow activated since then must not start a run."""
        task = _task(organization_id=self.org)
        await self._activate()
        await self.trigger(task)
        self.assertEqual(await self._runs(), [])

    async def test_paused_workflow_starts_nothing(self) -> None:
        await self._activate()
        await self.definitions.pause(self.org, self.slug)
        await self.trigger(_task(organization_id=self.org))
        self.assertEqual(await self._runs(), [])

    async def test_chain_stops_at_max_depth(self) -> None:
        await self._activate()

        def chained(depth: int) -> dict[str, typing.Any]:
            return _task(
                organization_id=self.org,
                origin_kind='task_completed',
                origin={'kind': 'task_completed', 'depth': depth},
            )

        await self.trigger(chained(task_trigger.MAX_DEPTH))
        self.assertEqual(await self._runs(), [])
        await self.trigger(chained(task_trigger.MAX_DEPTH - 1))
        [run] = await self._runs()
        self.assertEqual(run['origin']['depth'], task_trigger.MAX_DEPTH)

    async def test_delegated_child_keeps_the_chain_depth(self) -> None:
        """A child task that an agent delegates has origin ``task``; its
        depth comes from the root of its chain, so delegation cannot
        reset the loop guard."""
        await self._activate()
        root = _task(
            organization_id=self.org,
            origin_kind='task_completed',
            origin={'kind': 'task_completed', 'depth': task_trigger.MAX_DEPTH},
        )
        self.tasks.roots[root['id']] = root
        child = _task(
            organization_id=self.org,
            origin_kind='task',
            origin={'kind': 'task'},
            chain_id=root['id'],
        )
        await self.trigger(child)
        self.assertEqual(await self._runs(), [])

    async def test_missing_chain_root_starts_nothing(self) -> None:
        await self._activate()
        await self.trigger(
            _task(organization_id=self.org, chain_id=uuid.uuid4())
        )
        self.assertEqual(await self._runs(), [])
