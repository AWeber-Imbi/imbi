"""Tests for the plugin workflow step run endpoint (ADR 0032).

They run against the live Postgres that ``root:services`` boots: the
graph holds the organization and the project, and the call record is
real. The Integration and the plugin registry are patched.
"""

import asyncio
import datetime
import typing
import uuid
from unittest import mock

import fastapi
import httpx

from apps.api.tests import support
from imbi.api import models, workflows
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints import _helpers
from imbi.api.endpoints import integration_workflow_steps as endpoint
from imbi.api.maintenance import operations
from imbi.api.plugins import assignments, lifecycle
from imbi.common import graph
from imbi.common.plugins import base, errors
from imbi.common.plugins import registry as plugin_registry
from imbi.common.workflows import registry as workflow_steps
from libraries.common.tests.test_plugins.fixtures import step_plugin

PERMISSION = 'integration:workflow-step:run'


class RunStepTestCase(support.SharedAppAsyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'pws-{suffix}'
        self.team = f'team-{suffix}'
        self.project = f'proj-{suffix}'
        await graph.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.calls = workflows.plugin_calls.PluginCallStore(self.pool)
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})
            CREATE (t:Team {{id: {team}, slug: {team}, name: 'Ops'}})
            CREATE (t)-[:BELONGS_TO]->(o)
            CREATE (p:Project {{id: {project}, slug: {project}, name: 'P'}})
            CREATE (p)-[:OWNED_BY]->(t)
            RETURN o.id AS id
            """,
            {'org': self.org, 'team': self.team, 'project': self.project},
            ['id'],
        )
        self.auth = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-workflows', display_name='Imbi Workflows'
            ),
            auth_method='client_credentials',
            permissions={PERMISSION},
        )
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = lambda: self.auth
        overrides[organizations.member_org_id] = lambda: self.org
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[workflows.plugin_call_store] = lambda: self.calls
        self.integration: dict[str, typing.Any] = {
            'id': 'int-1',
            'slug': 'grafana-prod',
            'plugin': 'stepper',
            'options': {'url': 'https://grafana.example.com'},
            'capabilities': {'workflow-steps': {'enabled': True}},
            'encrypted_credentials': {},
        }
        entry = support.registry_entry(step_plugin.StepperPlugin.manifest)

        def get_plugin(slug: str) -> object:
            if slug != 'stepper':
                raise errors.PluginNotFoundError(slug)
            return entry

        for target, name, value in (
            (
                assignments,
                'org_integrations',
                mock.AsyncMock(
                    side_effect=lambda *_: {'int-1': self.integration}
                ),
            ),
            (
                lifecycle,
                'is_plugin_enabled',
                mock.AsyncMock(return_value=True),
            ),
            (plugin_registry, 'get_plugin', get_plugin),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )
        self.run_id = str(uuid.uuid4())

    async def _cleanup(self) -> None:
        await self.client.aclose()
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.plugin_step_calls'
                ' WHERE organization_id = %s',
                (self.org,),
            )
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': [self.org, self.team, self.project]},
            ['ok'],
        )
        await self.pool.close()
        await self.graph.close()

    async def _run(
        self,
        step: str = 'stepper.gather_metrics',
        *,
        key: str = 'k:1',
        params: dict[str, typing.Any] | None = None,
        **body: typing.Any,
    ) -> httpx.Response:
        return await self.client.post(
            f'/organizations/{self.org}/integrations/grafana-prod'
            f'/workflow-steps/{step}/run',
            json={
                'params': params
                if params is not None
                else {'datasource': 'prom', 'query': 'up'},
                'call': {
                    'run_id': self.run_id,
                    'workflow_slug': 'wf',
                    'node_id': 'n',
                    'attempt': 1,
                    'idempotency_key': key,
                },
                **body,
            },
            headers={'Idempotency-Key': key},
        )

    def _plugin(
        self, name: str = 'run_query', **kwargs: typing.Any
    ) -> mock.AsyncMock:
        handler = mock.AsyncMock(**kwargs)
        patcher = mock.patch.object(step_plugin, name, handler)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The registry resolves the callables once for each plugin.
        workflow_steps._plugin_types.cache_clear()
        self.addCleanup(workflow_steps._plugin_types.cache_clear)
        return handler

    def _error(self, response: httpx.Response) -> typing.Any:
        return response.json()['detail']

    async def test_runs_an_action(self) -> None:
        handler = self._plugin(
            return_value=base.StepResult(output={'value': 2.5})
        )
        response = await self._run()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {'output': {'value': 2.5}, 'port': '', 'poll': False, 'state': {}},
        )
        ctx, credentials, params, call = handler.await_args.args
        self.assertEqual(ctx.org_slug, self.org)
        self.assertEqual(ctx.integration_slug, 'grafana-prod')
        self.assertEqual(
            ctx.integration_options, {'url': 'https://grafana.example.com'}
        )
        self.assertEqual(credentials, {})
        self.assertIsInstance(params, step_plugin.QueryParams)
        self.assertEqual(call.run_id, self.run_id)

    async def test_needs_the_permission(self) -> None:
        self.auth.permissions = set()
        response = await self._run()
        self.assertEqual(response.status_code, 403)

    async def test_step_of_another_plugin(self) -> None:
        self.integration['plugin'] = 'other'
        response = await self._run()
        self.assertEqual(response.status_code, 404)
        self.integration['plugin'] = 'stepper'
        response = await self._run('stepper.no_such_step')
        self.assertEqual(response.status_code, 404)
        # The type names its plugin: a step of the same name with the
        # Integration of another plugin does not run.
        response = await self._run('other.gather_metrics')
        self.assertEqual(response.status_code, 404)

    async def test_unknown_integration(self) -> None:
        self.integration['slug'] = 'other'
        response = await self._run()
        self.assertEqual(response.status_code, 404)

    async def test_capability_off(self) -> None:
        self.integration['capabilities'] = {
            'workflow-steps': {'enabled': False}
        }
        response = await self._run()
        self.assertEqual(response.status_code, 409)

    async def test_project_must_be_in_the_org(self) -> None:
        handler = self._plugin(
            'run_threshold',
            return_value=base.StepResult(output={'value': 1}, port='Pass'),
        )
        params = {'query': 'up', 'below': 2}
        response = await self._run('stepper.metric_threshold', params=params)
        self.assertEqual(response.status_code, 422)
        response = await self._run(
            'stepper.metric_threshold', params=params, project_id='elsewhere'
        )
        self.assertEqual(response.status_code, 404)
        response = await self._run(
            'stepper.metric_threshold', params=params, project_id=self.project
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['port'], 'Pass')
        ctx = handler.await_args.args[0]
        self.assertEqual(ctx.project_slug, self.project)
        self.assertEqual(ctx.team_slug, self.team)
        self.assertEqual(ctx.service_connections, [])

    async def test_optional_project_loads_its_edges(self) -> None:
        handler = self._plugin(
            return_value=base.StepResult(output={'value': 1})
        )
        edges = [
            base.ServiceConnection(
                integration_slug='grafana-prod', identifier='x'
            )
        ]
        with mock.patch.object(
            _helpers,
            'lookup_project_exists_in',
            mock.AsyncMock(return_value=edges),
        ) as lookup:
            response = await self._run(project_id=self.project)
        self.assertEqual(response.status_code, 200, response.text)
        lookup.assert_awaited_once()
        ctx = handler.await_args.args[0]
        self.assertEqual(ctx.project_id, self.project)
        self.assertEqual(ctx.service_connections, edges)

    async def test_invalid_params(self) -> None:
        handler = self._plugin()
        response = await self._run(params={'query': 'up'})
        self.assertEqual(response.status_code, 422)
        handler.assert_not_awaited()

    async def test_repeat_of_a_key_gets_the_first_result(self) -> None:
        handler = self._plugin(
            return_value=base.StepResult(output={'value': 2.5})
        )
        first = await self._run()
        again = await self._run()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first.json())
        handler.assert_awaited_once()
        response = await self._run(key='k:2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(handler.await_count, 2)

    async def test_repeat_of_a_running_or_stale_call(self) -> None:
        handler = self._plugin()
        row, _ = await self.calls.start(
            {
                'organization_id': self.org,
                'principal': self.auth.principal_name,
                'idempotency_key': 'k:1',
                'run_id': self.run_id,
                'integration_slug': 'grafana-prod',
                'step_type': 'stepper.gather_metrics',
            },
            endpoint.STALE_AFTER,
        )
        response = await self._run()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self._error(response), {'error': 'call_in_progress', 'retry': True}
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE workflow_runtime.plugin_step_calls'
                " SET started_at = NOW() - INTERVAL '10 minutes'"
                ' WHERE id = %s',
                (row['id'],),
            )
        response = await self._run()
        self.assertEqual(
            self._error(response), {'error': 'outcome_unknown', 'retry': False}
        )
        handler.assert_not_awaited()

    async def test_poll(self) -> None:
        self._plugin(
            'run_threshold',
            return_value=base.StepResult(poll=True, state={'n': 1}),
        )
        response = await self._run(
            'stepper.metric_threshold',
            params={'query': 'up', 'below': 2},
            project_id=self.project,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {'output': None, 'port': '', 'poll': True, 'state': {'n': 1}},
        )

    async def test_poll_needs_poll_seconds(self) -> None:
        self._plugin(return_value=base.StepResult(poll=True))
        response = await self._run()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            self._error(response)['error'], 'plugin_result_invalid'
        )

    async def test_state_that_is_not_json_is_stored(self) -> None:
        handler = self._plugin(
            'run_threshold',
            return_value=base.StepResult(
                poll=True, state={'client': object()}
            ),
        )
        for _ in range(2):
            response = await self._run(
                'stepper.metric_threshold',
                params={'query': 'up', 'below': 2},
                project_id=self.project,
            )
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                self._error(response),
                {'error': 'plugin_result_invalid', 'retry': False},
            )
        handler.assert_awaited_once()

    async def test_bad_output_is_stored(self) -> None:
        handler = self._plugin(
            return_value=base.StepResult(output={'value': 'high'})
        )
        for _ in range(2):
            response = await self._run()
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                self._error(response),
                {'error': 'plugin_result_invalid', 'retry': False},
            )
        handler.assert_awaited_once()

    async def test_bad_port(self) -> None:
        self._plugin(
            return_value=base.StepResult(output={'value': 1}, port='Pass')
        )
        response = await self._run()
        self.assertEqual(
            self._error(response)['error'], 'plugin_result_invalid'
        )

    async def test_plugin_error_is_retried(self) -> None:
        self._plugin(side_effect=RuntimeError('boom'))
        response = await self._run()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            self._error(response), {'error': 'plugin_error', 'retry': True}
        )

    async def test_plugin_http_error_is_a_plugin_error(self) -> None:
        handler = self._plugin(
            side_effect=fastapi.HTTPException(429, detail='rate limited')
        )
        for _ in range(2):
            response = await self._run()
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                self._error(response),
                {'error': 'plugin_error', 'retry': True},
            )
        handler.assert_awaited_once()

    async def test_time_limit(self) -> None:
        async def slow(*_: typing.Any) -> base.StepResult:
            await asyncio.sleep(5)
            return base.StepResult(output={'value': 1})

        self._plugin(side_effect=slow)
        started = datetime.datetime.now(datetime.UTC)
        response = await self._run(time_limit_seconds=0.1)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(
            self._error(response), {'error': 'plugin_timeout', 'retry': True}
        )
        self.assertLess(
            (datetime.datetime.now(datetime.UTC) - started).total_seconds(), 4
        )

    async def test_request_size(self) -> None:
        response = await self._run(
            params={'datasource': 'prom', 'query': 'x' * endpoint.MAX_BYTES}
        )
        self.assertEqual(response.status_code, 413)

    async def test_request_size_counts_bytes(self) -> None:
        # Three bytes each in UTF-8: fewer characters than MAX_BYTES.
        response = await self._run(
            params={
                'datasource': 'prom',
                'query': '\u754c' * (endpoint.MAX_BYTES // 2),
            }
        )
        self.assertEqual(response.status_code, 413)

    async def test_prune(self) -> None:
        for key in ('old', 'new'):
            await self.calls.start(
                {
                    'organization_id': self.org,
                    'principal': 'imbi-workflows',
                    'idempotency_key': key,
                    'run_id': self.run_id,
                    'integration_slug': 'grafana-prod',
                    'step_type': 'stepper.gather_metrics',
                },
                endpoint.STALE_AFTER,
            )
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE workflow_runtime.plugin_step_calls'
                " SET started_at = NOW() - INTERVAL '91 days'"
                " WHERE organization_id = %s AND idempotency_key = 'old'",
                (self.org,),
            )
        ctx = mock.Mock()
        with mock.patch.object(
            workflows, 'plugin_call_store', return_value=self.calls
        ):
            outcome = await operations.execute_plugin_step_calls_prune(
                mock.AsyncMock(), mock.AsyncMock(), 'x', ctx=ctx
            )
        self.assertEqual(outcome, 'succeeded')
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT idempotency_key'
                ' FROM workflow_runtime.plugin_step_calls'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            self.assertEqual(await cur.fetchall(), [('new',)])
