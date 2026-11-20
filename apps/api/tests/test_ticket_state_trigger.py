"""Tests for the ``ticket_state_changed`` workflow trigger.

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
from imbi.api.workflows import runs as runs_module
from imbi.api.workflows import ticket_trigger, tickets
from imbi.common.workflows.registry import ticket_state_changed

# ``activated_at`` comes from the Postgres clock and the change time from
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
        **changes,
    }


class FakeTasks:
    """Returns chain roots and outbox rows from dicts, as the
    ``TicketStore``."""

    def __init__(self) -> None:
        self.roots: dict[uuid.UUID, dict[str, typing.Any]] = {}
        self.changes: dict[uuid.UUID, list[dict[str, typing.Any]]] = {}
        self.started: list[uuid.UUID] = []

    def change(
        self,
        task: dict[str, typing.Any],
        from_state: str | None = 'running',
        to_state: str = 'closed',
        created_at: datetime.datetime = CLOSED_AFTER_ACTIVATION,
        outcome: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, typing.Any]:
        """Add an outbox row for a change of ``task`` and return it.
        ``agent_id`` defaults to the agent of ``task``."""
        row = {
            'id': uuid.uuid4(),
            'ticket_id': task['id'],
            'from_state': from_state,
            'to_state': to_state,
            'outcome': outcome,
            'agent_id': agent_id or task['agent_id'],
            'created_at': created_at,
        }
        self.changes.setdefault(task['id'], []).append(row)
        return row

    async def state_changes(
        self, task_id: uuid.UUID
    ) -> list[dict[str, typing.Any]]:
        started = set(self.started)
        return [
            c for c in self.changes.get(task_id, []) if c['id'] not in started
        ]

    async def chain_root(
        self, task: dict[str, typing.Any]
    ) -> dict[str, typing.Any] | None:
        chain_id = task['chain_id'] or task['id']
        return task if chain_id == task['id'] else self.roots.get(chain_id)

    async def triggers_started(self, change_ids: list[uuid.UUID]) -> None:
        self.started.extend(change_ids)


class FakeGraph:
    """Returns the slugs of the org and the agent of a task."""

    async def execute(
        self, _query: str, params: dict[str, str], _columns: list[str]
    ) -> list[dict[str, str]]:
        return [{'org_slug': '"eng"', 'agent_slug': f'"{params["agent"]}"'}]


class ParamsTestCase(unittest.TestCase):
    def test_unknown_state_is_refused(self) -> None:
        for state in ('open_', 'started', 'done'):
            with self.assertRaises(pydantic.ValidationError):
                ticket_state_changed.Params.model_validate({'states': [state]})

    def test_unknown_outcome_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            ticket_state_changed.Params.model_validate({'outcomes': ['done']})


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
            [workflows.Trigger('done', ticket_trigger.KIND, params)],
        )

    async def _runs(self) -> list[dict[str, typing.Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT trigger_node_id, origin_kind, origin_id, origin,'
                ' payload FROM workflow_runtime.runs'
                ' WHERE organization_id = %s ORDER BY created_at',
                (self.org,),
            )
            names = [c.name for c in cur.description or []]
            return [
                dict(zip(names, r, strict=True)) for r in await cur.fetchall()
            ]

    async def _trigger(
        self, task: dict[str, typing.Any], **change: typing.Any
    ) -> dict[str, typing.Any]:
        """Add a change of ``task``, call the trigger, and return the
        change."""
        row = self.tasks.change(task, **change)
        await self.trigger(task)
        return row

    async def test_close_starts_one_run(self) -> None:
        await self._activate(
            agent_id='mender', outcomes=['failed_external', 'failed_at_gate']
        )
        task = _task(organization_id=self.org)
        config = mock.Mock(ui_url='https://imbi.example.com')
        with mock.patch.object(
            tickets.settings, 'get_server_config', return_value=config
        ):
            await self._trigger(task)
        self.assertEqual(
            await self._runs(),
            [
                {
                    'trigger_node_id': 'done',
                    'origin_kind': 'ticket_state_changed',
                    'origin_id': str(task['id']),
                    'origin': {
                        'kind': 'ticket_state_changed',
                        'task_id': 'T-7',
                        'depth': 1,
                        'lineage': str(task['id']),
                    },
                    'payload': {
                        'task_id': 'T-7',
                        'agent_id': 'mender',
                        'outcome': 'failed_external',
                        'from_state': 'running',
                        'to_state': 'closed',
                        'title': 'Fix the build',
                        'url': 'https://imbi.example.com/tickets/eng/T-7',
                        'project': 'web',
                        'agent': 'mender',
                        'cost_usd': 1.25,
                    },
                }
            ],
        )

    async def test_creation_starts_a_run_with_no_from_state(self) -> None:
        await self._activate(states=['created'])
        task = _task(organization_id=self.org, outcome=None)
        await self._trigger(task, from_state=None, to_state='queued')
        [run] = await self._runs()
        self.assertIsNone(run['payload']['from_state'])
        self.assertEqual(run['payload']['to_state'], 'queued')
        self.assertIsNone(run['payload']['outcome'])

    async def test_each_change_starts_its_own_run(self) -> None:
        await self._activate()
        task = _task(organization_id=self.org, outcome=None)
        self.tasks.change(task, from_state=None, to_state='queued')
        self.tasks.change(task, from_state='queued', to_state='running')
        await self.trigger(task)
        self.assertEqual(
            [
                (r['payload']['from_state'], r['payload']['to_state'])
                for r in await self._runs()
            ],
            [(None, 'queued'), ('queued', 'running')],
        )
        self.assertEqual(
            self.tasks.started,
            [c['id'] for c in self.tasks.changes[task['id']]],
        )

    async def test_retry_of_a_change_starts_no_second_run(self) -> None:
        await self._activate()
        task = _task(organization_id=self.org)
        change = self.tasks.change(task)
        await self.trigger(task)
        self.tasks.started.remove(change['id'])  # as if the delete failed
        await self.trigger(task)
        self.assertEqual(len(await self._runs()), 1)

    async def test_states_filter(self) -> None:
        await self._activate(states=['blocked', 'closed'])
        task = _task(organization_id=self.org, outcome=None)
        await self._trigger(task, from_state='queued', to_state='running')
        await self._trigger(task, from_state=None, to_state='queued')
        self.assertEqual(await self._runs(), [])
        await self._trigger(task, from_state='running', to_state='blocked')
        [run] = await self._runs()
        self.assertEqual(run['payload']['to_state'], 'blocked')

    async def test_outcomes_apply_only_to_a_close(self) -> None:
        await self._activate(outcomes=['done_acted'])
        task = _task(organization_id=self.org)
        await self._trigger(task)  # closes with failed_external
        self.assertEqual(await self._runs(), [])
        await self._trigger(task, from_state='queued', to_state='paused')
        [run] = await self._runs()
        self.assertEqual(run['payload']['to_state'], 'paused')

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
        await self._trigger(_task(organization_id=self.org))
        await self._trigger(_task(organization_id=self.org))
        await self._trigger(
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

    async def test_empty_filters_match_any_change(self) -> None:
        await self._activate()
        await self._trigger(
            _task(organization_id=self.org, agent_id='x', outcome='done_acted')
        )
        self.assertEqual(len(await self._runs()), 1)

    async def test_other_agent_or_outcome_starts_nothing(self) -> None:
        await self._activate(agent_id='mender', outcomes=['done_acted'])
        await self._trigger(_task(organization_id=self.org, agent_id='other'))
        await self._trigger(_task(organization_id=self.org))
        self.assertEqual(await self._runs(), [])

    async def test_no_change_does_nothing(self) -> None:
        await self._activate()
        with mock.patch.object(
            self.definitions, 'active_bindings', mock.AsyncMock()
        ) as bindings:
            await self.trigger(_task(organization_id=self.org))
        bindings.assert_not_called()

    async def test_change_without_outbox_row_does_nothing(self) -> None:
        await self._activate()
        task = _task(organization_id=self.org)
        self.tasks.change(task)
        await self.trigger(task, False)
        self.assertEqual(await self._runs(), [])
        self.assertEqual(self.tasks.started, [])

    async def test_outbox_row_stays_until_the_runs_start(self) -> None:
        """A failed run start keeps the outbox row for the sweep."""
        await self._activate()
        task = _task(organization_id=self.org)
        change = self.tasks.change(task)
        runs = typing.cast(typing.Any, self.trigger)._runs
        with mock.patch.object(
            runs, 'create', mock.AsyncMock(side_effect=RuntimeError('down'))
        ):
            await self.trigger(task)
        self.assertEqual(self.tasks.started, [])
        await self.trigger(task)
        self.assertEqual(self.tasks.started, [change['id']])
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
            change = await self._trigger(task)
        self.assertEqual(self.tasks.started, [change['id']])

    async def test_change_before_activation_starts_nothing(self) -> None:
        """The sweep calls the trigger again after the change; a
        workflow activated since then must not start a run."""
        await self._activate()
        await self._trigger(
            _task(organization_id=self.org),
            created_at=CLOSED_BEFORE_ACTIVATION,
        )
        self.assertEqual(await self._runs(), [])

    async def test_paused_workflow_starts_nothing(self) -> None:
        await self._activate()
        await self.definitions.pause(self.org, self.slug)
        await self._trigger(_task(organization_id=self.org))
        self.assertEqual(await self._runs(), [])

    async def test_chain_stops_at_max_depth(self) -> None:
        await self._activate()

        def chained(depth: int) -> dict[str, typing.Any]:
            return _task(
                organization_id=self.org,
                origin_kind=ticket_trigger.KIND,
                origin={'kind': ticket_trigger.KIND, 'depth': depth},
            )

        deepest = chained(ticket_trigger.MAX_DEPTH)
        change = await self._trigger(deepest)
        self.assertEqual(await self._runs(), [])
        self.assertEqual(self.tasks.started, [change['id']])
        await self._trigger(chained(ticket_trigger.MAX_DEPTH - 1))
        [run] = await self._runs()
        self.assertEqual(run['origin']['depth'], ticket_trigger.MAX_DEPTH)

    async def test_lineage_cap_stops_a_fan_out(self) -> None:
        """Every change of every ticket in a lineage can start a run, so
        the lineage caps the runs, not only the depth."""
        await self._activate()
        first = _task(organization_id=self.org)
        await self._trigger(first)
        [run] = await self._runs()
        lineage = run['origin']['lineage']
        self.assertEqual(lineage, str(first['id']))

        def made_by_a_run() -> dict[str, typing.Any]:
            # A ticket of an agent step copies the run origin.
            return _task(
                organization_id=self.org,
                origin_kind=ticket_trigger.KIND,
                origin={'kind': ticket_trigger.KIND, **run['origin']},
            )

        with mock.patch.object(ticket_trigger, 'MAX_LINEAGE_RUNS', 3):
            for _ in range(4):
                await self._trigger(made_by_a_run())
        found = await self._runs()
        self.assertEqual(len(found), 3)
        self.assertEqual({r['origin']['lineage'] for r in found}, {lineage})
        self.assertEqual(len(self.tasks.started), 5)  # every row cleared

    async def test_lineage_cap_applies_within_one_call(self) -> None:
        """One call with several changes stops at the cap."""
        await self._activate()
        task = _task(organization_id=self.org)
        for _ in range(3):
            self.tasks.change(task)
        with mock.patch.object(ticket_trigger, 'MAX_LINEAGE_RUNS', 2):
            await self.trigger(task)
        self.assertEqual(len(await self._runs()), 2)
        self.assertEqual(len(self.tasks.started), 3)  # every row cleared

    async def test_previous_release_close_is_not_a_creation(self) -> None:
        """A close row of the release before ``ticket_state_changed``
        has no ``from_state``; it must not match a creation filter."""
        await self._activate(states=['created'])
        await self._trigger(
            _task(organization_id=self.org), from_state=None, to_state='closed'
        )
        self.assertEqual(await self._runs(), [])

    async def test_outcome_comes_from_the_change(self) -> None:
        """A hook can get a snapshot of the ticket from before the
        close; the outbox row keeps the outcome of the close."""
        await self._activate(outcomes=['done_acted'])
        await self._trigger(
            _task(organization_id=self.org, outcome=None),
            outcome='done_acted',
        )
        [run] = await self._runs()
        self.assertEqual(run['payload']['outcome'], 'done_acted')

    async def test_agent_comes_from_the_change(self) -> None:
        """A handoff before the sweep changes the agent of the ticket;
        the outbox row keeps the agent that held it at the change."""
        await self._activate(agent_id='mender')
        await self._trigger(
            _task(organization_id=self.org, agent_id=None), agent_id='mender'
        )
        [run] = await self._runs()
        self.assertEqual(run['payload']['agent_id'], 'mender')
        self.assertEqual(run['payload']['agent'], 'mender')

    async def test_delegated_child_keeps_the_chain_depth(self) -> None:
        """A child ticket that an agent delegates has origin ``ticket``;
        its depth comes from the root of its chain, so delegation cannot
        reset the loop guard."""
        await self._activate()
        root = _task(
            organization_id=self.org,
            origin_kind=ticket_trigger.KIND,
            origin={
                'kind': ticket_trigger.KIND,
                'depth': ticket_trigger.MAX_DEPTH,
            },
        )
        self.tasks.roots[root['id']] = root
        child = _task(
            organization_id=self.org,
            origin_kind='ticket',
            origin={'kind': 'ticket'},
            chain_id=root['id'],
        )
        await self._trigger(child)
        self.assertEqual(await self._runs(), [])

    async def test_missing_chain_root_starts_nothing(self) -> None:
        await self._activate()
        await self._trigger(
            _task(organization_id=self.org, chain_id=uuid.uuid4())
        )
        self.assertEqual(await self._runs(), [])
