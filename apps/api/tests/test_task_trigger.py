"""Tests for the ``task_completed`` workflow trigger.

These run against the live Postgres that ``root:services`` boots.
"""

import datetime
import decimal
import typing
import unittest
import uuid
from unittest import mock

import pydantic
from psycopg.types import json as pg_json

from apps.api.tests.endpoints.test_workflow_runs import HeldRunStore
from imbi.api import workflows
from imbi.api.tickets import store as task_store
from imbi.api.workflows import runs as runs_module
from imbi.api.workflows import ticket_trigger, tickets
from imbi.common.workflows.registry import task_completed

# ``activated_at`` comes from the Postgres clock and ``closed_at`` from
# the test clock. Fixed times far from now keep their order when the two
# clocks are not the same.
CLOSED_AFTER_ACTIVATION = datetime.datetime(2999, 1, 1, tzinfo=datetime.UTC)
CLOSED_BEFORE_ACTIVATION = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)


def _task(**changes: typing.Any) -> dict[str, typing.Any]:
    return {
        'id': uuid.uuid4(),
        'short_id': 'T-7',
        'agent_id': 'mender',
        'outcome': 'failed_external',
        'title': 'Fix the build',
        'cost_total': decimal.Decimal('1.250000'),
        'projects': [{'project_id': 'p1', 'project_slug': 'web'}],
        'origin_kind': 'human',
        'origin': {'kind': 'human'},
        'chain_id': None,
        'closed_at': CLOSED_AFTER_ACTIVATION,
        'close_id': task_store.FIRST_CLOSE_ID,
        **changes,
    }


class FakeTasks:
    """Returns chain roots from a dict, as ``TicketStore.chain_root``."""

    def __init__(self) -> None:
        self.roots: dict[uuid.UUID, dict[str, typing.Any]] = {}
        self.started: list[uuid.UUID] = []
        self.closes: list[uuid.UUID] = []

    async def chain_root(
        self, task: dict[str, typing.Any]
    ) -> dict[str, typing.Any] | None:
        chain_id = task['chain_id'] or task['id']
        return task if chain_id == task['id'] else self.roots.get(chain_id)

    async def triggers_started(
        self, task_id: uuid.UUID, close_id: uuid.UUID
    ) -> None:
        self.started.append(task_id)
        self.closes.append(close_id)


class FakeGraph:
    """Returns the slugs of the org and the agent of a task."""

    async def execute(
        self, _query: str, params: dict[str, str], _columns: list[str]
    ) -> list[dict[str, str]]:
        return [{'org_slug': '"eng"', 'agent_slug': f'"{params["agent"]}"'}]


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
        self.trigger = ticket_trigger.TaskTrigger(
            self.definitions,
            HeldRunStore(self.pool),
            typing.cast(typing.Any, self.tasks),
            lambda: typing.cast(typing.Any, FakeGraph()),
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
        config = mock.Mock(ui_url='https://imbi.example.com')
        with mock.patch.object(
            tickets.settings, 'get_server_config', return_value=config
        ):
            await self.trigger(task)
            await self.trigger(task)  # a repeat starts no second run
        self.assertEqual(
            await self._runs(),
            [
                {
                    'trigger_node_id': 'done',
                    'origin_kind': 'ticket_closed',
                    'origin_id': str(task['id']),
                    'origin': {
                        'kind': 'ticket_closed',
                        'task_id': 'T-7',
                        'depth': 1,
                    },
                    'payload': {
                        'task_id': 'T-7',
                        'agent_id': 'mender',
                        'outcome': 'failed_external',
                        'title': 'Fix the build',
                        'url': 'https://imbi.example.com/tickets/eng/T-7',
                        'project': 'web',
                        'agent': 'mender',
                        'cost_usd': 1.25,
                    },
                }
            ],
        )

    async def test_each_close_of_a_reopened_ticket_starts_runs(self) -> None:
        """ADR 0028: a ticket that reopens and closes again starts its
        runs again, and a repeat of either close starts nothing."""
        await self._activate()
        first = _task(organization_id=self.org)
        second = {**first, 'close_id': uuid.uuid4()}
        for task in (first, second, first, second):
            await self.trigger(task)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT idempotency_key FROM workflow_runtime.runs'
                ' WHERE organization_id = %s ORDER BY created_at',
                (self.org,),
            )
            keys = [row[0] for row in await cur.fetchall()]
        # The first close keeps the key of the previous release.
        self.assertEqual(keys, ['done', f'done:{second["close_id"]}'])
        self.assertEqual(
            self.tasks.closes,
            [first['close_id'], second['close_id']] * 2,
        )

    async def test_old_kind_and_new_kind_start_one_run(self) -> None:
        # A sweep of the release before B retries with `task_completed`
        # (ADR 0028), before or after a pod of this release.
        await self._activate()
        for first, second in (
            ('task_completed', ticket_trigger.KIND),
            (ticket_trigger.KIND, 'task_completed'),
        ):
            task = _task(organization_id=self.org, id=uuid.uuid4())
            with mock.patch.object(ticket_trigger, 'KIND', first):
                await self.trigger(task)
            with mock.patch.object(ticket_trigger, 'KIND', second):
                await self.trigger(task)
            kinds = [
                run['origin_kind']
                for run in await self._runs()
                if run['origin_id'] == str(task['id'])
            ]
            self.assertEqual(kinds, [first])

    async def test_dedupe_key_skips_a_repeat(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE workflows.workflow_versions SET settings = %s'
                ' WHERE workflow_id = (SELECT id FROM workflows.workflows'
                ' WHERE organization_id = %s)',
                (
                    pg_json.Jsonb(
                        {
                            'dedupe_key': '{{ trigger.agent_id }}:'
                            '{{ trigger.outcome }}'
                        }
                    ),
                    self.org,
                ),
            )
        await self._activate(agent_id='mender')
        await self.trigger(_task(organization_id=self.org))
        await self.trigger(_task(organization_id=self.org))
        await self.trigger(
            _task(organization_id=self.org, outcome='done_acted')
        )
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT status, dedupe_key, duplicate_of IS NOT NULL'
                ' FROM workflow_runtime.runs WHERE organization_id = %s'
                ' ORDER BY created_at',
                (self.org,),
            )
            found = await cur.fetchall()
        self.assertEqual(
            found,
            [
                ('queued', 'mender:failed_external', False),
                ('skipped', 'mender:failed_external', True),
                ('queued', 'mender:done_acted', False),
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

    async def test_outbox_row_stays_until_the_runs_start(self) -> None:
        """A failed run start keeps the outbox row for the sweep."""
        await self._activate()
        task = _task(organization_id=self.org)
        runs = typing.cast(typing.Any, self.trigger)._runs
        with mock.patch.object(
            runs, 'create', mock.AsyncMock(side_effect=RuntimeError('down'))
        ):
            await self.trigger(task)
        self.assertEqual(self.tasks.started, [])
        await self.trigger(task)
        self.assertEqual(self.tasks.started, [task['id']])
        self.assertEqual(len(await self._runs()), 1)

    async def test_inactive_workflow_clears_the_outbox_row(self) -> None:
        await self._activate()
        task = _task(organization_id=self.org)
        runs = typing.cast(typing.Any, self.trigger)._runs
        with mock.patch.object(
            runs,
            'create',
            mock.AsyncMock(side_effect=runs_module.NotActive('gone')),
        ):
            await self.trigger(task)
        self.assertEqual(self.tasks.started, [task['id']])

    async def test_task_closed_before_activation_starts_nothing(self) -> None:
        """The sweep calls the trigger again after the task closed; a
        workflow activated since then must not start a run."""
        await self._activate()
        await self.trigger(
            _task(organization_id=self.org, closed_at=CLOSED_BEFORE_ACTIVATION)
        )
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

        await self.trigger(chained(ticket_trigger.MAX_DEPTH))
        self.assertEqual(await self._runs(), [])
        await self.trigger(chained(ticket_trigger.MAX_DEPTH - 1))
        [run] = await self._runs()
        self.assertEqual(run['origin']['depth'], ticket_trigger.MAX_DEPTH)

    async def test_delegated_child_keeps_the_chain_depth(self) -> None:
        """A child task that an agent delegates has origin ``task``; its
        depth comes from the root of its chain, so delegation cannot
        reset the loop guard."""
        await self._activate()
        root = _task(
            organization_id=self.org,
            origin_kind='task_completed',
            origin={
                'kind': 'task_completed',
                'depth': ticket_trigger.MAX_DEPTH,
            },
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
