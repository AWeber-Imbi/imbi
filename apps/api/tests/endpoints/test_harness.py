"""Tests for runner pools, dispatch, and agent tokens (ADR 0022).

These run against the live Postgres that ``root:services`` boots. Each
pool serves only the organizations of its test, so a claim never takes
a task of another test.
"""

import asyncio
import json
import typing
import uuid
from unittest import mock

import httpx

from apps.api.tests.endpoints import test_agent_task_harness
from apps.api.tests.endpoints.test_agent_task_log import ClickHouseTestCase
from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.endpoints import agent_task_harness
from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import sweeper

new_id = test_agent_task_harness.new_id


class RunnerTestCase(test_agent_task_harness.HarnessTestCase):
    """Fixtures: a pool for ``org`` with the label ``general``."""

    pool_labels: typing.ClassVar[list[str]] = ['general']

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.pool_account = models.ServiceAccount(
            id=f'pool-{self.org}',
            slug=f'pool-{self.org}',
            display_name='Pool',
        )
        await self.graph.execute(
            'CREATE (s:ServiceAccount {{id: {slug}, slug: {slug},'
            ' display_name: {slug}, is_active: true}}) RETURN s.id AS id',
            {'slug': self.pool_account.slug},
            ['id'],
        )
        # The owner of a parent task must be able to make agent tasks
        # (the check of child task creation), as with a seeded role.
        await self.graph.execute(
            'MERGE (p:Permission {{name: "agent_task:create"}})'
            ' CREATE (r:Role {{slug: {role}, name: {role}}})'
            ' CREATE (r)-[:GRANTS]->(p)'
            ' WITH r MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->()'
            ' SET m.role = {role} RETURN 1 AS ok',
            {'role': f'runner-{self.org}', 'email': self.email},
            ['ok'],
        )
        self.addAsyncCleanup(self._cleanup_harness)
        self.pool_name = await self.make_pool(self.pool_labels, [self.org])

    async def _cleanup_harness(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM harness.pools WHERE name LIKE %s',
                (f'%{self.org}',),
            )
            await conn.execute(
                'DELETE FROM harness.tool_call_counts WHERE agent_id = %s',
                (self.agent_id,),
            )
        await self.graph.execute(
            'MATCH (s:ServiceAccount {{slug: {slug}}}) DETACH DELETE s'
            ' RETURN 1 AS ok',
            {'slug': self.pool_account.slug},
            ['ok'],
        )
        await self.graph.execute(
            'MATCH (r:Role {{slug: {role}}}) DETACH DELETE r RETURN 1 AS ok',
            {'role': f'runner-{self.org}'},
            ['ok'],
        )

    async def make_pool(
        self, labels: list[str], orgs: list[str], name: str = 'general'
    ) -> str:
        pool = await self.harness.create_pool(
            f'{name}-{self.org}',
            description=None,
            labels=labels,
            organization_ids=orgs,
            service_account=self.pool_account.slug,
        )
        return str(pool['name'])

    async def register(self, pool: str | None = None) -> dict[str, typing.Any]:
        """Register a runner of ``pool`` with the pool credential."""
        self.act_as(self.pool_account)
        try:
            response = await self.client.post(
                '/harness/runners',
                json={
                    'pool': pool or self.pool_name,
                    'instance': 'pod-1',
                    'image_version': '1.0',
                },
            )
        finally:
            self.act_as(self.account)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def runner_post(
        self, runner: dict[str, typing.Any], path: str, **kwargs: typing.Any
    ) -> httpx.Response:
        return await self.client.post(
            f'/harness/runners/{runner["runner_id"]}/{path}',
            headers={'Authorization': f'Bearer {runner["runner_token"]}'},
            **kwargs,
        )

    async def claim(
        self, runner: dict[str, typing.Any]
    ) -> dict[str, typing.Any] | None:
        response = await self.runner_post(runner, 'claim')
        if response.status_code == 204:
            return None
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def as_agent(
        self,
        token: str,
        method: str,
        path: str,
        body: typing.Any = None,
        org: str | None = None,
    ) -> httpx.Response:
        """Call an ADR 0020 harness route with an agent token."""
        return await self.client.request(
            method,
            self.url(path, org),
            json=body,
            headers={'Authorization': f'Bearer {token}'},
        )

    async def expire(self, runner: dict[str, typing.Any]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE harness.runners'
                " SET lease_expires_at = NOW() - interval '1 second'"
                ' WHERE id = %s',
                (uuid.UUID(runner['runner_id']),),
            )

    async def end_grace(self, chain_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE harness.chains'
                " SET fenced_at = NOW() - interval '1 hour'"
                ' WHERE root_task_id = %s',
                (uuid.UUID(chain_id),),
            )

    async def make_version(
        self, snapshot: dict[str, typing.Any], agent_id: str | None = None
    ) -> None:
        """Make version 3 (the pinned version) of an agent."""
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}})'
            ' CREATE (v:AgentVersion {{id: {vid}, agent_id: {id}, n: 3,'
            ' snapshot: {snapshot}, created_by: "x"}})-[:VERSION_OF]->(a)'
            ' RETURN v.id AS id',
            {
                'id': agent_id or self.agent_id,
                'vid': new_id(),
                'snapshot': json.dumps(snapshot),
            },
            ['id'],
        )

    def fencer(self, result: bool) -> sweeper.Fencer:
        """Register a fencer that returns ``result`` for this test."""
        calls: list[uuid.UUID] = []

        async def fence(runner_id: uuid.UUID) -> bool:
            calls.append(runner_id)
            return result

        sweeper.register_fencer(fence)
        self.addCleanup(sweeper.unregister_fencer, fence)
        fence.calls = calls  # type: ignore[attr-defined]
        return fence


class RegisterTests(RunnerTestCase):
    async def test_only_the_pool_account_registers(self) -> None:
        response = await self.client.post(
            '/harness/runners', json={'pool': self.pool_name}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['error'], 'pool_forbidden')
        runner = await self.register()
        self.assertTrue(runner['runner_token'].startswith('ihr_'))
        self.assertTrue(runner['executor_token'].startswith('ihe_'))
        self.assertEqual(runner['labels'], ['general'])

    async def test_runner_credential_is_checked(self) -> None:
        runner = await self.register()
        other = await self.register()
        response = await self.client.post(
            f'/harness/runners/{runner["runner_id"]}/heartbeat',
            headers={'Authorization': f'Bearer {other["runner_token"]}'},
        )
        self.assertEqual(response.status_code, 401, response.text)
        response = await self.client.post(
            f'/harness/runners/{runner["runner_id"]}/heartbeat',
            headers={'Authorization': f'Bearer {runner["executor_token"]}'},
        )
        self.assertEqual(response.status_code, 401, response.text)
        response = await self.runner_post(runner, 'heartbeat')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['state'], 'idle')

    async def test_executor_credential_finds_its_runner(self) -> None:
        runner = await self.register()
        row = await self.harness.runner_by_executor_credential(
            runner['executor_token']
        )
        assert row is not None
        self.assertEqual(str(row['id']), runner['runner_id'])
        self.assertIsNone(
            await self.harness.runner_by_executor_credential(
                runner['runner_token']
            )
        )


class ClaimTests(RunnerTestCase):
    async def test_two_clients_never_claim_one_task(self) -> None:
        self.act_as_user()
        for _ in range(5):
            response = await self.create_task()
            self.assertEqual(response.status_code, 201, response.text)
        self.act_as(self.account)
        # Two clients, each with three runners, claim at the same time.
        runners = [await self.register() for _ in range(6)]
        claims = await asyncio.gather(*(self.claim(r) for r in runners))
        short_ids = [claim['task']['short_id'] for claim in claims if claim]
        self.assertEqual(len(short_ids), 6)
        self.assertEqual(
            sorted(short_ids), sorted(f'T-{n}' for n in range(1, 7))
        )
        # The queue is empty now; a seventh runner gets nothing.
        self.assertIsNone(await self.claim(await self.register()))
        # A busy runner cannot claim a second chain.
        response = await self.runner_post(runners[0], 'claim')
        self.assertEqual(response.status_code, 409, response.text)

    async def test_claim_returns_bundle_and_token(self) -> None:
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}})'
            ' CREATE (v:AgentVersion {{id: {vid}, agent_id: {id}, n: 3,'
            ' snapshot: {snapshot}, created_by: "x"}})-[:VERSION_OF]->(a)'
            ' RETURN v.id AS id',
            {
                'id': self.agent_id,
                'vid': new_id(),
                'snapshot': json.dumps(
                    {'slug': 'triage', 'prompt_ref': 'ops/triage@prod'}
                ),
            },
            ['id'],
        )
        claim = await self.claim(await self.register())
        assert claim is not None
        self.assertEqual(claim['task']['short_id'], 'T-1')
        self.assertEqual(claim['chain_id'], self.task['id'])
        self.assertEqual(claim['attempt'], 1)
        self.assertEqual(claim['organization_slug'], self.org)
        self.assertEqual(claim['bundle']['agent_version'], 3)
        self.assertEqual(claim['bundle']['prompt_ref'], 'ops/triage@prod')
        self.assertEqual(claim['bundle']['prompt_version'], 7)

    async def test_long_poll_waits_for_a_task(self) -> None:
        runner = await self.register()
        self.assertIsNotNone(await self.claim(runner))
        idle = await self.register()
        response = await self.runner_post(idle, 'claim', params={'wait': 1})
        self.assertEqual(response.status_code, 204, response.text)

    async def test_outside_the_allowlist_gets_nothing(self) -> None:
        pool = await self.make_pool(['general'], [self.other_org], 'other')
        self.assertIsNone(await self.claim(await self.register(pool)))
        self.assertIsNotNone(await self.claim(await self.register()))

    async def test_pool_changes_apply_to_live_runners(self) -> None:
        runner = await self.register()
        await self.harness.update_pool(
            self.pool_name, {'organization_ids': [self.other_org]}
        )
        self.assertIsNone(await self.claim(runner))
        await self.harness.update_pool(
            self.pool_name, {'organization_ids': [self.org]}
        )
        self.assertIsNotNone(await self.claim(runner))

    async def test_agent_disabled_during_a_long_poll(self) -> None:
        self.act_as_user()
        await self.client.post(self.url('T-1/pause'))
        self.act_as(self.account)
        runner = await self.register()
        poll = asyncio.create_task(
            self.runner_post(runner, 'claim', params={'wait': 3})
        )
        await asyncio.sleep(0.5)
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}}) SET a.enabled = false'
            ' RETURN a.id AS id',
            {'id': self.agent_id},
            ['id'],
        )
        self.act_as_user()
        response = await self.client.post(self.url('T-1/resume'))
        self.act_as(self.account)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.task_row())['status'], 'queued')
        response = await poll
        self.assertEqual(response.status_code, 204, response.text)

    async def test_disabled_agent_is_not_claimed(self) -> None:
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}}) SET a.enabled = false'
            ' RETURN a.id AS id',
            {'id': self.agent_id},
            ['id'],
        )
        self.assertIsNone(await self.claim(await self.register()))

    async def test_paused_and_running_tasks_are_not_claimed(self) -> None:
        self.act_as_user()
        await self.client.post(self.url('T-1/pause'))
        self.act_as(self.account)
        self.assertIsNone(await self.claim(await self.register()))


class FailedClaimTests(RunnerTestCase):
    async def runner_row(self, runner: dict[str, typing.Any]) -> typing.Any:
        (row,) = [
            r
            for r in await self.harness.runners([self.pool_name])
            if str(r['id']) == runner['runner_id']
        ]
        return row

    async def test_task_without_service_account_is_closed(self) -> None:
        await self.graph.execute(
            'MATCH (s:ServiceAccount {{id: {id}}}) DETACH DELETE s'
            ' RETURN 1 AS ok',
            {'id': self.account.id},
            ['ok'],
        )
        runner = await self.register()
        self.assertIsNone(await self.claim(runner))
        task = await self.task_row()
        self.assertEqual(task['status'], 'closed')
        self.assertEqual(task['outcome'], 'unhandled_no_actor')
        self.assertEqual(task['outcome_reason'], 'service_account_missing')
        row = await self.runner_row(runner)
        self.assertEqual(row['state'], 'idle')
        self.assertIsNone(row['chain_id'])
        chain = await self.harness.chain(uuid.UUID(self.task['id']))
        assert chain is not None
        self.assertEqual(chain['state'], 'done')

    async def test_failed_response_releases_the_claim(self) -> None:
        runner = await self.register()
        with (
            mock.patch.object(
                harness_api, '_bundle', side_effect=RuntimeError('boom')
            ),
            self.assertRaises(RuntimeError),
        ):
            await self.runner_post(runner, 'claim')
        row = await self.runner_row(runner)
        self.assertEqual(row['state'], 'idle')
        chain = await self.harness.chain(uuid.UUID(self.task['id']))
        assert chain is not None
        self.assertEqual(chain['state'], 'queued')
        self.assertEqual((await self.task_row())['status'], 'queued')
        # The same runner claims the task when the error is gone.
        claim = await self.claim(runner)
        assert claim is not None
        self.assertEqual(claim['task']['short_id'], 'T-1')
        self.assertEqual(claim['attempt'], 1)


class LabelTests(RunnerTestCase):
    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'task_budget': '1',
        'required_labels': ['gpu'],
    }

    async def test_runner_without_the_label_gets_nothing(self) -> None:
        self.assertIsNone(await self.claim(await self.register()))
        pool = await self.make_pool(['general', 'gpu'], [self.org], 'gpu')
        claim = await self.claim(await self.register(pool))
        assert claim is not None
        self.assertEqual(claim['task']['short_id'], 'T-1')

    async def test_label_removed_from_the_pool_applies_at_once(self) -> None:
        pool = await self.make_pool(['general', 'gpu'], [self.org], 'gpu')
        runner = await self.register(pool)
        await self.harness.update_pool(pool, {'labels': ['general']})
        self.assertIsNone(await self.claim(runner))


class ConcurrencyTests(RunnerTestCase):
    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'task_budget': '1',
        'max_concurrent_tasks': 1,
    }

    async def test_agent_limit_holds_across_runners(self) -> None:
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        first, second = await asyncio.gather(
            self.claim(await self.register()),
            self.claim(await self.register()),
        )
        self.assertEqual(
            sorted(c is None for c in (first, second)), [False, True]
        )


class AgentTokenTests(RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.token: str = claim['agent_token']

    async def test_token_works_for_its_chain(self) -> None:
        response = await self.as_agent(
            self.token, 'POST', 'T-1/sessions', {'session_key': 's'}
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.as_agent(
            self.token,
            'POST',
            'T-1/events',
            {'events': [{'event_id': new_id(), 'type': 'turn'}]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.get(
            '/harness/tasks/T-1/events',
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[-1]['type'], 'turn')

    async def test_token_for_chain_a_cannot_write_chain_b(self) -> None:
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        other = await self.claim(await self.register())
        assert other is not None
        self.assertEqual(other['task']['short_id'], 'T-2')
        for path, body in await test_agent_task_harness.AccessTests.routes(
            typing.cast('typing.Any', self)
        ):
            with self.subTest(path=path):
                response = await self.as_agent(
                    self.token, 'POST', f'T-2/{path}', body
                )
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(
                    response.json()['detail']['error'], 'chain_forbidden'
                )
        response = await self.client.get(
            '/harness/tasks/T-2/events',
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_token_is_refused_in_another_organization(self) -> None:
        response = await self.as_agent(
            self.token,
            'POST',
            'T-1/sessions',
            {'session_key': 's'},
            org=self.other_org,
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_token_of_another_agent_is_refused(self) -> None:
        helper_id = await self.make_agent('helper', name='Helper')
        await self.make_version({'subagents': [{'agent_id': helper_id}]})
        response = await self.client.post(
            '/harness/tasks/T-1/children',
            json={
                'agent_slug': 'helper',
                'title': 'Help',
                'description': 'Help out.',
            },
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        child = response.json()['short_id']
        # The token of the parent's agent cannot work the child.
        response = await self.as_agent(
            self.token, 'POST', f'{child}/sessions', {'session_key': 's'}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'agent_task_forbidden'
        )

    async def test_harness_task_routes_need_membership(self) -> None:
        await self.graph.execute(
            'MATCH (s:ServiceAccount {{id: {id}}})-[m:MEMBER_OF]->()'
            ' DELETE m RETURN 1 AS ok',
            {'id': self.account.id},
            ['ok'],
        )
        response = await self.client.get(
            '/harness/tasks/T-1/events',
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'organization_forbidden'
        )

    async def test_audience_is_refused_on_other_routes(self) -> None:
        overrides = self.test_app.dependency_overrides
        del overrides[permissions.get_current_user]
        for path in ('', 'T-1', 'T-1/events'):
            with self.subTest(path=path):
                response = await self.client.get(
                    self.url(path),
                    headers={'Authorization': f'Bearer {self.token}'},
                )
                self.assertEqual(response.status_code, 401, response.text)
        response = await self.client.get(
            '/harness/pools',
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 401, response.text)

    async def test_pinned_chain_refuses_other_credentials(self) -> None:
        # The client credential of the agent's own service account.
        response = await self.post('sessions', {'session_key': 's'})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['error'], 'chain_pinned')

    async def test_token_ends_with_the_runner(self) -> None:
        response = await self.runner_post(self.runner, 'finish')
        self.assertEqual(response.status_code, 200, response.text)
        # The task is open, so the chain is fenced, not done.
        self.assertEqual(response.json()['chain_state'], 'fencing')
        response = await self.as_agent(
            self.token, 'POST', 'T-1/sessions', {'session_key': 's'}
        )
        self.assertEqual(response.status_code, 401, response.text)
        response = await self.runner_post(self.runner, 'heartbeat')
        self.assertEqual(response.status_code, 401, response.text)


class FencingTests(RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.token: str = claim['agent_token']
        self.chain_id: str = claim['chain_id']
        response = await self.as_agent(
            self.token, 'POST', 'T-1/sessions', {'session_key': 's'}
        )
        self.assertEqual(response.status_code, 201, response.text)

    async def chain(self) -> dict[str, typing.Any]:
        chain = await self.harness.chain(uuid.UUID(self.chain_id))
        assert chain is not None
        return chain

    async def test_requeue_waits_for_fencers_and_grace(self) -> None:
        fence = self.fencer(True)
        await self.expire(self.runner)
        await sweeper.sweep_once(self.harness)
        # The fencers ran, but the grace period has not passed.
        chain = await self.chain()
        self.assertEqual(chain['state'], 'fencing')
        self.assertEqual(chain['attempt'], 2)
        self.assertIsNotNone(chain['fencers_ok_at'])
        self.assertEqual(fence.calls, [uuid.UUID(self.runner['runner_id'])])  # type: ignore[attr-defined]
        self.assertEqual((await self.task_row())['status'], 'running')
        # The old attempt is refused at once.
        response = await self.as_agent(
            self.token,
            'POST',
            'T-1/events',
            {'events': [{'event_id': new_id(), 'type': 'turn'}]},
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()['detail']['error'], 'stale_attempt')
        # No other runner can claim the chain yet.
        self.assertIsNone(await self.claim(await self.register()))

        await self.end_grace(self.chain_id)
        await sweeper.sweep_once(self.harness)
        self.assertEqual((await self.chain())['state'], 'queued')
        task = await self.task_row()
        self.assertEqual(task['status'], 'queued')
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events[-3:]],
            ['session.closed', 'attempt_marker', 'state.changed'],
        )
        marker = events[-2]
        self.assertEqual(
            marker['payload'], {'attempt': 2, 'reason': 'runner_lost'}
        )
        # A new runner claims the chain in attempt 2.
        claim = await self.claim(await self.register())
        assert claim is not None
        self.assertEqual(claim['task']['short_id'], 'T-1')
        self.assertEqual(claim['attempt'], 2)
        # The token of attempt 1 stays refused.
        response = await self.as_agent(
            self.token, 'POST', 'T-1/sessions', {'session_key': 's2'}
        )
        self.assertEqual(response.status_code, 401, response.text)
        response = await self.as_agent(
            claim['agent_token'], 'POST', 'T-1/sessions', {'session_key': 's2'}
        )
        self.assertEqual(response.status_code, 201, response.text)

    async def test_failing_fencer_keeps_the_chain_fenced(self) -> None:
        self.fencer(True)
        failing = self.fencer(False)
        await self.expire(self.runner)
        await sweeper.sweep_once(self.harness)
        await self.end_grace(self.chain_id)
        await sweeper.sweep_once(self.harness)
        chain = await self.chain()
        self.assertEqual(chain['state'], 'stuck')
        self.assertIn('fence', chain['fence_error'])
        self.assertEqual((await self.task_row())['status'], 'running')
        self.assertNotIn(
            'attempt_marker', [e['type'] for e in await self.events()]
        )
        self.assertIsNone(await self.claim(await self.register()))
        # The stuck chain shows on the runner list.
        (runner,) = [
            r
            for r in await self.harness.runners([self.pool_name])
            if str(r['id']) == self.runner['runner_id']
        ]
        self.assertEqual(runner['state'], 'fenced')
        self.assertEqual(runner['chain_state'], 'stuck')
        # When the fencer works again, the chain goes back to the queue.
        sweeper.unregister_fencer(failing)
        await sweeper.sweep_once(self.harness)
        self.assertEqual((await self.chain())['state'], 'queued')
        self.assertEqual((await self.task_row())['status'], 'queued')

    async def test_stalled_fencer_times_out_as_a_failure(self) -> None:
        async def stall(runner_id: uuid.UUID) -> bool:
            await asyncio.sleep(5)
            return True

        sweeper.register_fencer(stall)
        self.addCleanup(sweeper.unregister_fencer, stall)
        await self.expire(self.runner)
        with mock.patch.object(sweeper, 'FENCER_TIMEOUT_SECONDS', 0.05):
            await sweeper.sweep_once(self.harness)
        chain = await self.chain()
        self.assertEqual(chain['state'], 'stuck')
        self.assertIn('stall', chain['fence_error'])

    async def test_one_bad_chain_does_not_block_the_rest(self) -> None:
        self.fencer(True)
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        other = await self.register()
        claim = await self.claim(other)
        assert claim is not None
        await self.expire(self.runner)
        await self.expire(other)
        real = self.harness.set_fence_result

        async def fail_first(
            chain: dict[str, typing.Any], error: str | None
        ) -> typing.Any:
            if str(chain['root_task_id']) == self.chain_id:
                raise RuntimeError('bad chain')
            return await real(chain, error)

        with mock.patch.object(
            self.harness, 'set_fence_result', side_effect=fail_first
        ):
            await sweeper.sweep_once(self.harness)
        bad = await self.chain()
        good = await self.harness.chain(uuid.UUID(claim['chain_id']))
        assert good is not None
        self.assertIsNone(bad['fencers_ok_at'])
        self.assertIsNotNone(good['fencers_ok_at'])

    async def test_finish_after_all_tasks_close_is_done(self) -> None:
        response = await self.as_agent(
            self.token, 'POST', 'T-1/outcome', {'outcome': 'done_acted'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.runner_post(self.runner, 'finish')
        self.assertEqual(response.json()['chain_state'], 'done')


class ChildTaskTests(RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.token: str = claim['agent_token']
        self.chain_id: str = claim['chain_id']

    async def child(
        self, agent_slug: str, **body: typing.Any
    ) -> httpx.Response:
        return await self.client.post(
            '/harness/tasks/T-1/children',
            json={
                'agent_slug': agent_slug,
                'title': 'Help',
                'description': 'Help out.',
                **body,
            },
            headers={'Authorization': f'Bearer {self.token}'},
        )

    async def test_child_needs_the_runner_labels(self) -> None:
        gpu_id = await self.make_agent(
            'gpu-helper', name='GPU', settings={'required_labels': ['gpu']}
        )
        await self.make_version({'subagents': [{'agent_id': gpu_id}]})
        response = await self.child('gpu-helper')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'runner_label_missing'
        )

    async def test_child_agent_must_be_a_subagent(self) -> None:
        helper_id = await self.make_agent('helper', name='Helper')
        await self.make_agent('stranger', name='Stranger')
        await self.make_version({'subagents': [{'agent_id': helper_id}]})
        response = await self.child('stranger')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'subagent_forbidden'
        )
        self.assertEqual(
            (await self.child('helper')).status_code, 201, 'a subagent'
        )

    async def test_owner_must_still_make_tasks(self) -> None:
        helper_id = await self.make_agent('helper', name='Helper')
        await self.make_version({'subagents': [{'agent_id': helper_id}]})
        await self.graph.execute(
            'MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->'
            '(:Organization {{slug: {org}}}) DELETE m RETURN 1 AS ok',
            {'email': self.email, 'org': self.org},
            ['ok'],
        )
        response = await self.child('helper')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['error'], 'owner_forbidden')

    async def test_only_the_chain_runner_claims_the_child(self) -> None:
        helper_id = await self.make_agent('helper', name='Helper')
        await self.make_version({'subagents': [{'agent_id': helper_id}]})
        response = await self.child('helper', idempotency_key='k')
        self.assertEqual(response.status_code, 201, response.text)
        child = response.json()
        self.assertEqual(child['chain_id'], self.chain_id)
        self.assertEqual(child['origin']['kind'], 'task')
        self.assertEqual(child['origin']['task_id'], self.task['id'])
        self.assertEqual(child['agent_id'], helper_id)
        repeat = await self.child('helper', idempotency_key='k')
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['id'], child['id'])
        # Another runner cannot claim it.
        self.assertIsNone(await self.claim(await self.register()))
        response = await self.runner_post(self.runner, 'chain/claim')
        self.assertEqual(response.status_code, 200, response.text)
        claim = response.json()
        self.assertEqual(claim['task']['short_id'], child['short_id'])
        # The child's token works for the child, as its own agent.
        response = await self.as_agent(
            claim['agent_token'],
            'POST',
            f'{child["short_id"]}/sessions',
            {'session_key': 's'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        # A child is claimed one time per attempt.
        response = await self.runner_post(self.runner, 'chain/claim')
        self.assertEqual(response.status_code, 204, response.text)


class RateLimitTests(RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}})'
            ' CREATE (v:AgentVersion {{id: {vid}, agent_id: {id}, n: 3,'
            ' snapshot: {snapshot}, created_by: "x"}})-[:VERSION_OF]->(a)'
            ' RETURN v.id AS id',
            {
                'id': self.agent_id,
                'vid': new_id(),
                'snapshot': json.dumps(
                    {
                        'tools': {
                            'gh.pr': {
                                'rate_limit': {'count': 2, 'per': 'hour'}
                            },
                            'gh.read': {},
                        }
                    }
                ),
            },
            ['id'],
        )
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        self.tokens: list[str] = []
        for _ in range(2):
            claim = await self.claim(await self.register())
            assert claim is not None
            self.tokens.append(claim['agent_token'])

    async def check(self, token: str, short_id: str, tool: str) -> typing.Any:
        response = await self.client.post(
            f'/harness/tasks/{short_id}/tool-calls/check',
            json={'tool_key': tool},
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_limit_counts_across_runners(self) -> None:
        first = await self.check(self.tokens[0], 'T-1', 'gh.pr')
        second = await self.check(self.tokens[1], 'T-2', 'gh.pr')
        third = await self.check(self.tokens[0], 'T-1', 'gh.pr')
        self.assertEqual(
            [first['allowed'], second['allowed'], third['allowed']],
            [True, True, False],
        )
        self.assertEqual(second['count'], 2)
        self.assertEqual(third['reason'], 'rate_limited')
        self.assertEqual(third['limit'], 2)
        self.assertEqual(third['per'], 'hour')

    async def test_unlimited_and_unknown_tools(self) -> None:
        for _ in range(3):
            self.assertTrue(
                (await self.check(self.tokens[0], 'T-1', 'gh.read'))['allowed']
            )
        verdict = await self.check(self.tokens[0], 'T-1', 'gh.nope')
        self.assertFalse(verdict['allowed'])
        self.assertEqual(verdict['reason'], 'tool_not_configured')


class LargeEventTests(RunnerTestCase, ClickHouseTestCase):
    """A large tool result goes to ClickHouse as continuation events."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.token: str = claim['agent_token']

    async def send(
        self, events: list[dict[str, typing.Any]]
    ) -> httpx.Response:
        return await self.as_agent(
            self.token, 'POST', 'T-1/events', {'events': events}
        )

    async def test_three_mib_result_lands_as_three_parts(self) -> None:
        part = 'x' * (agent_task_harness.MAX_LARGE_PAYLOAD_BYTES - 200)
        events = [
            {
                'event_id': new_id(),
                'type': 'tool.called',
                'payload': {
                    'call_id': 'c-1',
                    'part': n,
                    'parts': 3,
                    'result': part,
                },
            }
            for n in (1, 2, 3)
        ]
        response = await self.send(events)
        self.assertEqual(response.status_code, 201, response.text)
        stored = await self.stored_events(self.task['id'])
        parts = [
            json.loads(row['payload'])
            for row in stored
            if row['type'] == 'tool.called'
        ]
        self.assertEqual([p['part'] for p in parts], [1, 2, 3])
        self.assertEqual(sum(len(p['result']) for p in parts), 3 * len(part))

    async def test_limits_and_continuation_rules(self) -> None:
        too_big = 'x' * agent_task_harness.MAX_LARGE_PAYLOAD_BYTES
        response = await self.send(
            [{'event_id': new_id(), 'type': 'turn', 'payload': {'b': too_big}}]
        )
        self.assertEqual(response.status_code, 413, response.text)
        for payload in (
            {'call_id': 'c', 'part': 4, 'parts': 3},
            {'call_id': 'c', 'part': 0, 'parts': 3},
            {'part': 1, 'parts': 2},
            {'call_id': 'c', 'part': '1', 'parts': 2},
        ):
            with self.subTest(payload=payload):
                response = await self.send(
                    [
                        {
                            'event_id': new_id(),
                            'type': 'tool.called',
                            'payload': payload,
                        }
                    ]
                )
                self.assertEqual(response.status_code, 422, response.text)
        response = await self.send(
            [
                {
                    'event_id': new_id(),
                    'type': 'todos.updated',
                    'payload': {'call_id': 'c', 'part': 1, 'parts': 2},
                }
            ]
        )
        self.assertEqual(response.status_code, 422, response.text)


class PoolApiTests(RunnerTestCase):
    async def test_platform_admin_manages_pools(self) -> None:
        self.act_as_user()
        body = {
            'name': f'x-{self.org}',
            'labels': ['general', 'general'],
            'organizations': [self.org],
            'service_account': self.pool_account.slug,
        }
        response = await self.client.post('/harness/pools', json=body)
        self.assertEqual(response.status_code, 403, response.text)
        # A permission is not enough: an org admin could grant it.
        self.permissions.add('harness_pool:write')
        response = await self.client.post('/harness/pools', json=body)
        self.assertEqual(response.status_code, 403, response.text)
        self.user.is_admin = True
        response = await self.client.post('/harness/pools', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['labels'], ['general'])
        self.assertEqual(response.json()['organizations'], [self.org])
        response = await self.client.post('/harness/pools', json=body)
        self.assertEqual(response.status_code, 409, response.text)
        response = await self.client.post(
            '/harness/pools',
            json={**body, 'name': 'y', 'organizations': ['?']},
        )
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.patch(
            f'/harness/pools/x-{self.org}', json={'labels': ['gpu']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['labels'], ['gpu'])
        # A live runner holds the pool.
        await self.register(f'x-{self.org}')
        self.act_as_user()
        response = await self.client.delete(f'/harness/pools/x-{self.org}')
        self.assertEqual(response.status_code, 409, response.text)
        response = await self.client.delete(f'/harness/pools/{self.pool_name}')
        self.assertEqual(response.status_code, 204, response.text)

    async def test_members_see_only_pools_and_chains_of_their_org(
        self,
    ) -> None:
        other_pool = await self.make_pool([], [self.other_org], 'other')
        runner = await self.register()
        await self.claim(runner)
        self.act_as_user()
        response = await self.client.get(
            '/harness/pools', params={'organization': self.org}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions.add('harness_pool:read')
        response = await self.client.get('/harness/pools')
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.get(
            '/harness/pools', params={'organization': self.org}
        )
        self.assertEqual(response.status_code, 200, response.text)
        pools = {p['name']: p for p in response.json()}
        self.assertIn(self.pool_name, pools)
        self.assertNotIn(other_pool, pools)
        (item,) = [
            r
            for r in pools[self.pool_name]['runners']
            if r['id'] == runner['runner_id']
        ]
        self.assertEqual(item['state'], 'busy')
        self.assertEqual(item['chain']['short_id'], 'T-1')
        self.assertEqual(item['chain']['organization_slug'], self.org)
        self.assertIsNone(pools[self.pool_name]['service_account'])
        # A platform administrator needs no membership.
        self.user.is_admin = True
        response = await self.client.get(
            '/harness/pools', params={'organization': self.foreign_org}
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.get(
            '/harness/pools', params={'organization': 'no-such-org'}
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.user.is_admin = False
        response = await self.client.get(
            '/harness/pools', params={'organization': self.foreign_org}
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_members_do_not_see_other_orgs_of_a_pool(self) -> None:
        shared = await self.make_pool(
            ['general'], [self.org, self.other_org], 'shared'
        )
        own = await self.register(shared)
        self.assertIsNotNone(await self.claim(own))  # T-1 of org
        await self.make_agent(org=self.other_org)
        self.act_as_user()
        response = await self.create_task(org=self.other_org)
        self.assertEqual(response.status_code, 201, response.text)
        foreign = await self.register(shared)
        claim = await self.claim(foreign)
        assert claim is not None
        self.assertEqual(claim['organization_slug'], self.other_org)
        self.act_as_user()
        self.permissions.add('harness_pool:read')
        response = await self.client.get(
            '/harness/pools', params={'organization': self.org}
        )
        self.assertEqual(response.status_code, 200, response.text)
        (pool,) = [p for p in response.json() if p['name'] == shared]
        self.assertEqual(pool['organizations'], [self.org])
        self.assertIsNone(pool['service_account'])
        runners = {r['id']: r for r in pool['runners']}
        self.assertEqual(runners[own['runner_id']]['instance'], 'pod-1')
        self.assertIsNotNone(runners[own['runner_id']]['chain'])
        hidden = runners[foreign['runner_id']]
        self.assertEqual(hidden['state'], 'busy')
        self.assertIsNone(hidden['chain'])
        self.assertIsNone(hidden['instance'])
        self.assertIsNone(hidden['image_version'])
        # A platform administrator sees everything.
        self.user.is_admin = True
        response = await self.client.get('/harness/pools')
        (pool,) = [p for p in response.json() if p['name'] == shared]
        self.assertEqual(
            pool['organizations'], sorted([self.org, self.other_org])
        )
        self.assertEqual(pool['service_account'], self.pool_account.slug)
