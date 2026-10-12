"""Tests for the workflow run log in ClickHouse (ADR 0021, Run history).

These write through the real code and read the rows back from the live
ClickHouse that ``root:services`` boots.
:func:`apps.api.tests.support.sink_to_clickhouse` puts each publish
straight into its table, as the Iggy sink would.
"""

import datetime
import uuid
from unittest import mock

from apps.api.tests import support
from apps.api.tests.endpoints import test_workflow_runs
from imbi.api.workflows import sweeper
from imbi.common import clickhouse, iggy
from imbi.common.clickhouse import client
from imbi.common.workflows import history, runtime


class RunHistoryTestCase(test_workflow_runs.WorkflowRunTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # The ClickHouse client binds to the loop that opened it, and each
        # test has its own loop, so each test takes its own client.
        previous = client.Clickhouse._instance
        client.Clickhouse._instance = None

        async def restore() -> None:
            await clickhouse.aclose()
            client.Clickhouse._instance = previous

        self.addAsyncCleanup(restore)
        await clickhouse.initialize()
        await clickhouse.setup_schema()

    async def _start(self, url: str) -> str:
        response = await self.client.post(
            f'{url}/runs', json={'inputs': {'version': '1.2.3'}}
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()['id']

    async def _close(self, run_id: str, status: str) -> None:
        """Do what the engine does to start the trigger and close a run."""
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                'INSERT INTO workflow_runtime.step_runs (run_id, node_id,'
                ' node_key, node_type, title, status, port, started_at,'
                " finished_at) VALUES (%s, 'start', 'start', 'manual',"
                " 'Start', 'succeeded', 0, NOW(), NOW())",
                (run_id,),
            )
            cur = await conn.execute(
                "SELECT to_jsonb(s) - ARRAY['run_id', 'state',"
                " 'call_started_at'] FROM workflow_runtime.step_runs AS s"
                ' WHERE run_id = %s',
                (run_id,),
            )
            row = await cur.fetchone()
            assert row is not None
            await runtime.append_event(
                conn, uuid.UUID(run_id), 'step.succeeded', row[0]
            )
            await conn.execute(
                'UPDATE workflow_runtime.runs SET status = %s,'
                ' started_at = NOW(), closed_at = NOW() WHERE id = %s',
                (status, run_id),
            )
            await runtime.append_event(
                conn, uuid.UUID(run_id), 'run.closed', {'status': status}
            )


class SweepTestCase(RunHistoryTestCase):
    async def test_sweep_republishes_then_archives(self) -> None:
        url = await self._workflow()
        # Every publish is lost: the sweep is what fills ClickHouse.
        with mock.patch.object(
            iggy, 'publish_rows', side_effect=iggy.PublishError('down')
        ):
            run_id = await self._start(url)
        await self._close(run_id, 'succeeded')
        before = (await self.client.get(f'{url}/runs/{run_id}')).json()
        self.assertEqual([s['status'] for s in before['steps']], ['succeeded'])

        with (
            support.sink_to_clickhouse(),
            mock.patch.object(sweeper, '_try_sweep_lock', return_value=True),
        ):
            result = await sweeper.sweep_once(self.runs)
            self.assertGreaterEqual(result.republished_events, 3)
            self.assertEqual(result.archived, 0)
            result = await sweeper.sweep_once(self.runs)
        self.assertEqual(result.archived, 1)

        after = (await self.client.get(f'{url}/runs/{run_id}')).json()
        self.assertIsNotNone(after['log_archived_at'])
        self.assertEqual(after['status'], 'succeeded')
        self.assertEqual(after['steps'], before['steps'])
        async with self.pool.connection() as conn:
            for table in ('run_events', 'step_runs'):
                cur = await conn.execute(
                    f'SELECT COUNT(*) FROM workflow_runtime.{table}'
                    ' WHERE run_id = %s',
                    (run_id,),
                )
                self.assertEqual(await cur.fetchone(), (0,), table)

        workflows = (await self.client.get(self.base + '/')).json()
        self.assertEqual(workflows[0]['runs_30d'], 1)
        self.assertEqual(workflows[0]['last_run_status'], 'succeeded')

    async def test_open_run_is_not_archived(self) -> None:
        url = await self._workflow()
        with support.sink_to_clickhouse():
            run_id = await self._start(url)
        with (
            support.sink_to_clickhouse(),
            mock.patch.object(sweeper, '_try_sweep_lock', return_value=True),
        ):
            result = await sweeper.sweep_once(self.runs)
        self.assertEqual(result.archived, 0)
        run = (await self.client.get(f'{url}/runs/{run_id}')).json()
        self.assertIsNone(run['log_archived_at'])


class SummaryTestCase(RunHistoryTestCase):
    async def test_latest_row_wins_over_unmerged_parts(self) -> None:
        """The two-row pattern: reads take the latest row per run."""
        command = client.Clickhouse.get_instance().command
        await command('SYSTEM STOP MERGES imbi.workflow_runs')
        self.addAsyncCleanup(command, 'SYSTEM START MERGES imbi.workflow_runs')
        workflow_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.UTC)
        run = {
            'id': uuid.uuid4(),
            'organization_id': self.org,
            'workflow_id': workflow_id,
            'version': 1,
            'origin_kind': 'human',
            'origin_id': self.email,
            'status': 'running',
            'error': None,
            'created_at': now,
            'started_at': now,
            'closed_at': None,
            'last_seq': 2,
        }
        with support.sink_to_clickhouse():
            # Two inserts are two parts, so the rows are not merged.
            await history.publish(run, [], summary=True)
            await history.publish(
                {**run, 'status': 'failed', 'closed_at': now, 'last_seq': 7},
                [],
                summary=True,
            )
        raw = await clickhouse.query(
            'SELECT count() AS rows FROM imbi.workflow_runs'
            ' WHERE organization_id = {org:String}',
            {'org': self.org},
        )
        self.assertEqual(raw[0]['rows'], 2)
        stats = await history.stats(self.org)
        self.assertEqual(stats[workflow_id]['runs_30d'], 1)
        self.assertEqual(stats[workflow_id]['last_status'], 'failed')
        self.assertEqual(
            await history.summaries(self.org, [str(run['id'])]),
            {str(run['id']): 'failed'},
        )


class AttentionTestCase(test_workflow_runs.WorkflowRunTestCase):
    async def test_failed_and_stuck_runs(self) -> None:
        url = await self._workflow()
        ids = []
        for _ in range(3):
            response = await self.client.post(
                f'{url}/runs', json={'inputs': {'version': '1'}}
            )
            ids.append(response.json()['id'])
        failed, stuck, fresh = ids
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'failed',"
                " error = 'timeout', closed_at = NOW() WHERE id = %s",
                (failed,),
            )
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'running',"
                " due_at = NOW() - INTERVAL '10 minutes' WHERE id = %s",
                (stuck,),
            )
        response = await self.client.get(
            f'/organizations/{self.org}/workflow-runs/attention'
        )
        self.assertEqual(response.status_code, 200, response.text)
        found = {r['id']: r for r in response.json()}
        self.assertEqual(set(found), {failed, stuck})
        self.assertNotIn(fresh, found)
        self.assertEqual(found[failed]['reason'], 'failed')
        self.assertEqual(found[failed]['error'], 'timeout')
        self.assertEqual(found[stuck]['reason'], 'stuck')
        self.assertEqual(found[stuck]['workflow_slug'], 'deploy-guard')
