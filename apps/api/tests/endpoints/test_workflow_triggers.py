"""Tests for schedule and webhook triggers in imbi-api (ADR 0021).

Activation and pause write the desired trigger bindings; the run
endpoint takes runs from the scheduler and the gateway. The reconciler
that syncs the bindings is tested in ``apps/workflows``.
"""

import typing

import httpx

from apps.api.tests.endpoints import test_workflow_runs as base
from imbi.api import models
from imbi.api.auth import organizations, permissions


def _graph(webhook: bool = True) -> dict[str, typing.Any]:
    nodes = [
        base._node('tick', 'schedule', {'cron': '0 9 * * *'}),
        base._node('pause', 'wait', {'duration': '1m'}),
    ]
    edges = [{'source': 'tick', 'port': 0, 'target': 'pause'}]
    if webhook:
        nodes.append(base._node('hook', 'webhook', {'webhook_id': 'wh-1'}))
        edges.append({'source': 'hook', 'port': 0, 'target': 'pause'})
    return {'nodes': nodes, 'edges': edges}


def _service(slug: str) -> permissions.AuthContext:
    return permissions.AuthContext(
        service_account=models.ServiceAccount(slug=slug, display_name=slug),
        auth_method='client_credentials',
        permissions={'workflow:run'},
    )


class TriggerTestCase(base.WorkflowRunTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        response = await self.client.post(
            self.base + '/',
            json={
                'name': 'Nightly',
                'owner_team_slug': self.team,
                'graph': _graph(),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.url = f'{self.base}/nightly'
        response = await self.client.post(f'{self.url}/activate')
        self.assertEqual(response.status_code, 200, response.text)
        self.workflow = response.json()
        self.addAsyncCleanup(self._drop_bindings)
        self.user_auth = self.test_app.dependency_overrides[
            permissions.get_current_user
        ]

    async def _drop_bindings(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflows.trigger_bindings'
                ' WHERE organization_id = %s',
                (self.org,),
            )

    def _as(self, slug: str) -> None:
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = lambda: _service(slug)
        overrides[organizations.member_org_id] = lambda: self.org

    async def _bindings(self) -> dict[str, dict[str, typing.Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT node_id, enabled, removed, sync_state'
                ' FROM workflows.trigger_bindings WHERE organization_id = %s',
                (self.org,),
            )
            return {
                row[0]: {
                    'enabled': row[1],
                    'removed': row[2],
                    'sync_state': row[3],
                }
                for row in await cur.fetchall()
            }

    async def _sync(self, node_id: str, target_id: str) -> None:
        """Record a binding as the reconciler does after a sync."""
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflows.trigger_bindings SET sync_state = 'synced',"
                ' target_id = %s WHERE organization_id = %s AND node_id = %s',
                (target_id, self.org, node_id),
            )

    async def _run_count(self) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT COUNT(*) FROM workflow_runtime.runs'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0


class BindingTestCase(TriggerTestCase):
    async def test_activation_pause_and_delete_write_bindings(self) -> None:
        self.assertEqual(
            [
                (b['node_id'], b['type'], b['enabled'], b['sync_state'])
                for b in self.workflow['bindings']
            ],
            [
                ('hook', 'webhook', True, 'pending'),
                ('tick', 'schedule', True, 'pending'),
            ],
        )

        response = await self.client.post(f'{self.url}/pause')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [b['enabled'] for b in response.json()['bindings']],
            [False, False],
        )

        # A new version without the webhook trigger.
        response = await self.client.put(
            self.url,
            json={
                'name': 'Nightly',
                'owner_team_slug': self.team,
                'graph': _graph(webhook=False),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        await self._sync('tick', 'task-1')
        response = await self.client.post(f'{self.url}/activate')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [
                (b['node_id'], b['enabled'], b['sync_state'], b['target_id'])
                for b in response.json()['bindings']
            ],
            [('tick', True, 'pending', 'task-1')],
        )
        self.assertTrue((await self._bindings())['hook']['removed'])

        response = await self.client.delete(self.url)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(
            {k: v['removed'] for k, v in (await self._bindings()).items()},
            {'hook': True, 'tick': True},
        )


class ScheduleRunTestCase(TriggerTestCase):
    def _post(
        self, task: str = 'task-1', key: str = 'run-1', trigger: str = 'tick'
    ) -> typing.Awaitable[httpx.Response]:
        return self.client.post(
            f'{self.url}/runs',
            json={
                'trigger': trigger,
                'payload': {'fired_at': '2026-10-12T09:00:00Z'},
            },
            headers={'X-Imbi-Scheduled-Task': task, 'Idempotency-Key': key},
        )

    async def test_one_firing_one_run_and_redelivery_none(self) -> None:
        await self._sync('tick', 'task-1')
        self._as('imbi-scheduler')
        response = await self._post()
        self.assertEqual(response.status_code, 202, response.text)
        run = response.json()
        self.assertEqual(run['origin_kind'], 'schedule')
        self.assertEqual(run['origin_id'], 'task-1')
        self.assertEqual(
            run['origin'],
            {'kind': 'schedule', 'scheduled_task_id': 'task-1'},
        )
        self.assertEqual(run['trigger_node_id'], 'tick')
        self.assertEqual(run['payload'], {'fired_at': '2026-10-12T09:00:00Z'})

        # A retry of the same scheduler run.
        response = await self._post()
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()['id'], run['id'])
        self.assertEqual(await self._run_count(), 1)

        # The next firing.
        response = await self._post(key='run-2')
        self.assertNotEqual(response.json()['id'], run['id'])
        self.assertEqual(await self._run_count(), 2)

    async def test_only_the_binding_task_starts_runs(self) -> None:
        self._as('imbi-scheduler')
        # Not synced yet: the binding records no task.
        response = await self._post()
        self.assertEqual(response.status_code, 403, response.text)
        await self._sync('tick', 'task-1')
        response = await self._post(task='someone-elses-task')
        self.assertEqual(response.status_code, 403, response.text)
        response = await self._post(trigger='hook')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(await self._run_count(), 0)

    async def test_paused_workflow_starts_no_run(self) -> None:
        await self._sync('tick', 'task-1')
        response = await self.client.post(f'{self.url}/pause')
        self.assertEqual(response.status_code, 200, response.text)
        self._as('imbi-scheduler')
        response = await self._post()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(await self._run_count(), 0)


class WebhookRunTestCase(TriggerTestCase):
    def _post(
        self, delivery: str = 'd-1', webhook: str = 'wh-1'
    ) -> typing.Awaitable[httpx.Response]:
        return self.client.post(
            f'{self.url}/runs',
            json={'trigger': 'hook', 'payload': {'payload': {'a': 1}}},
            headers={'X-Imbi-Webhook': webhook, 'X-Imbi-Delivery': delivery},
        )

    async def test_one_delivery_one_run_and_redelivery_none(self) -> None:
        self._as('imbi-gateway')
        response = await self._post()
        self.assertEqual(response.status_code, 202, response.text)
        run = response.json()
        self.assertEqual(run['origin_kind'], 'webhook')
        self.assertEqual(run['origin_id'], 'wh-1')
        self.assertEqual(
            run['origin'],
            {'kind': 'webhook', 'webhook_id': 'wh-1', 'delivery_id': 'd-1'},
        )
        self.assertEqual(run['payload'], {'payload': {'a': 1}})

        response = await self._post()
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()['id'], run['id'])
        self.assertEqual(await self._run_count(), 1)

        response = await self._post(delivery='d-2')
        self.assertNotEqual(response.json()['id'], run['id'])
        self.assertEqual(await self._run_count(), 2)

    async def test_other_webhook_is_refused(self) -> None:
        self._as('imbi-gateway')
        response = await self._post(webhook='wh-2')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(await self._run_count(), 0)

    async def test_paused_workflow_starts_no_run(self) -> None:
        response = await self.client.post(f'{self.url}/pause')
        self.assertEqual(response.status_code, 200, response.text)
        self._as('imbi-gateway')
        response = await self._post()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(await self._run_count(), 0)


class OriginTestCase(TriggerTestCase):
    async def test_person_cannot_name_an_origin(self) -> None:
        response = await self.client.post(
            f'{self.url}/runs',
            json={'trigger': 'hook'},
            headers={'X-Imbi-Webhook': 'wh-1', 'X-Imbi-Delivery': 'd-1'},
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_other_service_account_is_refused(self) -> None:
        self._as('imbi-workflows')
        response = await self.client.post(
            f'{self.url}/runs', json={'trigger': 'tick'}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(await self._run_count(), 0)
