"""Tests for the AI model call record and its prune.

The store tests run against the live Postgres that ``root:services``
boots.
"""

import typing
import unittest
import uuid
from unittest import mock

from imbi.api import model_calls, workflows
from imbi.api.maintenance import operations
from imbi.common import relational


def _call(org: str, key: str | None) -> dict[str, typing.Any]:
    return {
        'organization_id': org,
        'principal': 'imbi-workflows',
        'origin': 'workflow' if key else 'preview',
        'run_id': None,
        'node_id': None,
        'attempt': None,
        'idempotency_key': key,
        'prompt_ref': 'workflows/acme.wf.node@1',
        'prompt_version': 1,
        'content_sha256': 'abc',
        'model': 'default-chat',
        'model_id': 'claude-opus-5',
        'ai_model_id': None,
        'driver': 'anthropic',
        'system': 'Be brief.',
        'messages': [{'role': 'user', 'content': 'Hi'}],
        'output_schema': None,
    }


class ModelCallStoreTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.org = f'mc-{uuid.uuid4().hex[:10]}'
        await workflows.initialize()
        await model_calls.initialize()
        self.pool = model_calls.create_pool()
        await self.pool.open()
        self.addAsyncCleanup(self._cleanup)
        self.store = model_calls.ModelCallStore(self.pool)

    async def _cleanup(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM ai_runtime.ai_model_calls'
                ' WHERE organization_id = %s',
                (self.org,),
            )
        await self.pool.close()

    async def _age(self, call_id: uuid.UUID, interval: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE ai_runtime.ai_model_calls'
                ' SET started_at = NOW() - %s::interval WHERE id = %s',
                (interval, call_id),
            )

    async def test_repeat_of_a_key_returns_the_first_call(self) -> None:
        first, new = await self.store.start(_call(self.org, 'r:n:1'), 60)
        self.assertTrue(new)
        self.assertEqual(first['status'], 'running')
        await self.store.finish(
            first['id'],
            'succeeded',
            text='Done',
            usage={'input_tokens': 1, 'output_tokens': 2},
        )
        again, new = await self.store.start(_call(self.org, 'r:n:1'), 60)
        self.assertFalse(new)
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(again['status'], 'succeeded')
        self.assertEqual(again['text'], 'Done')
        self.assertEqual(again['usage']['output_tokens'], 2)

    async def test_repeat_finds_the_call_by_key(self) -> None:
        self.assertIsNone(
            await self.store.repeat(self.org, 'imbi-workflows', 'r:n:3', 60)
        )
        first, _ = await self.store.start(_call(self.org, 'r:n:3'), 60)
        await self._age(first['id'], '2 minutes')
        row = await self.store.repeat(self.org, 'imbi-workflows', 'r:n:3', 60)
        assert row is not None
        self.assertEqual(row['id'], first['id'])
        self.assertEqual(row['status'], 'outcome_unknown')

    async def test_start_rejects_a_deleted_organization(self) -> None:
        async with self.pool.connection() as conn:
            await relational.mark_organization_deleted(conn, self.org)
        self.addAsyncCleanup(self._undelete)
        with self.assertRaises(relational.OrganizationDeleted):
            await self.store.start(_call(self.org, 'r:n:4'), 60)

    async def _undelete(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM organizations.deleted WHERE organization_id = %s',
                (self.org,),
            )

    async def test_previews_never_conflict(self) -> None:
        _, first = await self.store.start(_call(self.org, None), 60)
        _, second = await self.store.start(_call(self.org, None), 60)
        self.assertTrue(first)
        self.assertTrue(second)

    async def test_stale_running_call_is_outcome_unknown(self) -> None:
        first, _ = await self.store.start(_call(self.org, 'r:n:2'), 60)
        again, _ = await self.store.start(_call(self.org, 'r:n:2'), 60)
        self.assertEqual(again['status'], 'running')
        await self._age(first['id'], '2 minutes')
        again, _ = await self.store.start(_call(self.org, 'r:n:2'), 60)
        self.assertEqual(again['status'], 'outcome_unknown')
        # A late failure does not change it.
        await self.store.finish(first['id'], 'failed', error='x')
        again, _ = await self.store.start(_call(self.org, 'r:n:2'), 60)
        self.assertEqual(again['status'], 'outcome_unknown')
        # A late success replaces it: the answer stays available.
        await self.store.finish(first['id'], 'succeeded', text='late')
        again, _ = await self.store.start(_call(self.org, 'r:n:2'), 60)
        self.assertEqual(again['status'], 'succeeded')
        self.assertEqual(again['text'], 'late')

    async def test_prune_deletes_old_calls(self) -> None:
        old, _ = await self.store.start(_call(self.org, 'r:n:old'), 60)
        recent, _ = await self.store.start(_call(self.org, 'r:n:new'), 60)
        await self._age(old['id'], '91 days')
        self.assertGreaterEqual(await self.store.prune(), 1)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT id FROM ai_runtime.ai_model_calls'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            left = [row[0] for row in await cur.fetchall()]
        self.assertEqual(left, [recent['id']])

    async def test_prune_keeps_the_calls_of_an_open_run(self) -> None:
        # A run has no upper time limit, and its steps reuse their keys.
        await workflows.initialize()
        run_id = uuid.uuid4()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO workflow_runtime.runs (id, organization_id,'
                ' workflow_id, version, trigger_node_id, origin_kind,'
                " origin_id, activated_by) VALUES (%s, %s, %s, 1, 'n',"
                " 'human', 'u', 'u')",
                (run_id, self.org, uuid.uuid4()),
            )
        self.addAsyncCleanup(self._delete_runs)
        row, _ = await self.store.start(
            {**_call(self.org, f'{run_id}:n:1'), 'run_id': str(run_id)}, 60
        )
        await self._age(row['id'], '91 days')
        await self.store.prune()
        self.assertIsNotNone(
            await self.store.repeat(
                self.org, 'imbi-workflows', f'{run_id}:n:1', 60
            )
        )

    async def _delete_runs(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.runs WHERE organization_id = %s',
                (self.org,),
            )


class PruneOperationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_prunes_with_the_store(self) -> None:
        store = mock.AsyncMock()
        store.prune.return_value = 3
        ctx = mock.Mock()
        with mock.patch.object(model_calls, 'get_store', return_value=store):
            items = await operations.enumerate_ai_model_calls_prune(
                mock.AsyncMock()
            )
            outcome = await operations.execute_ai_model_calls_prune(
                mock.AsyncMock(), mock.AsyncMock(), items[0], ctx=ctx
            )
        self.assertEqual(outcome, 'succeeded')
        store.prune.assert_awaited_once()
        self.assertEqual(ctx.log.record.call_args.kwargs['deleted'], 3)
