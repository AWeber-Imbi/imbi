"""Tests for the plugin workflow step choices endpoint (ADR 0032)."""

import asyncio
import datetime
import typing
from unittest import mock

from fastapi import testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints import integration_workflow_step_choices as module
from imbi.common import graph
from imbi.common.plugins import base
from libraries.common.tests.test_plugins.fixtures import step_plugin

URL = (
    '/organizations/myorg/integrations/stepper-prod'
    '/workflow-steps/stepper.gather_metrics/choices'
)


def _integration(**over: typing.Any) -> dict[str, typing.Any]:
    node: dict[str, typing.Any] = {
        'plugin': 'stepper',
        'slug': 'stepper-prod',
        'status': 'active',
        'options': {'host': 'grafana.example.com'},
        'capabilities': {
            'workflow-steps': {'enabled': True, 'options': {'a': 1}}
        },
        'encrypted_credentials': {'token': 'cipher'},
    }
    node.update(over)
    return node


class ChoicesTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.auth = permissions.AuthContext(
            user=models.User(
                email='dev@example.com',
                display_name='Dev',
                is_active=True,
                is_admin=False,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='s',
            auth_method='jwt',
            permissions={'workflow:write', 'integration:read'},
        )
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = lambda: self.auth
        overrides[organizations.member_org_id] = lambda: 'org-id'
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.db.execute.return_value = [{'integration': _integration()}]
        overrides[graph._inject_graph] = lambda: self.db
        self.choices = mock.AsyncMock(
            return_value=[base.Choice(value='prom', label='Prometheus')]
        )
        descriptor = step_plugin.query_descriptor(choices=self.choices)

        class Steps(base.WorkflowStepsCapability):
            @classmethod
            def steps(cls) -> list[base.WorkflowStepDescriptor]:
                return [descriptor]

        manifest = step_plugin.StepperPlugin.manifest.model_copy(
            update={
                'capabilities': [
                    base.Capability(
                        kind='workflow-steps',
                        label='Workflow steps',
                        project_scoped=False,
                        handler=Steps,
                    )
                ]
            }
        )
        for patcher in (
            mock.patch.object(
                module.integration_workflow_steps.plugin_registry,
                'get_plugin',
                return_value=support.registry_entry(manifest),
            ),
            mock.patch.object(
                module.lifecycle, 'is_plugin_enabled', return_value=True
            ),
            mock.patch.object(
                module.credentials,
                'decrypt_integration_credentials',
                return_value={'token': 'secret'},
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = testclient.TestClient(self.test_app)

    def _post(self, field: str = 'datasource') -> typing.Any:
        return self.client.post(
            URL, json={'field': field, 'params': {'query': 'up'}}
        )

    def test_returns_choices(self) -> None:
        response = self._post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [{'value': 'prom', 'label': 'Prometheus', 'description': None}],
        )
        ctx, secrets, field, params = self.choices.await_args.args
        self.assertEqual(ctx.org_slug, 'myorg')
        self.assertEqual(ctx.integration_slug, 'stepper-prod')
        self.assertEqual(
            ctx.integration_options, {'host': 'grafana.example.com'}
        )
        self.assertEqual(ctx.capability_options, {'a': 1})
        self.assertEqual(secrets, {'token': 'secret'})
        self.assertEqual((field, params), ('datasource', {'query': 'up'}))

    def test_caps_choices(self) -> None:
        self.choices.return_value = [
            base.Choice(value=str(i), label=str(i)) for i in range(1001)
        ]
        self.assertEqual(len(self._post().json()), 1000)

    def test_field_without_choices(self) -> None:
        self.assertEqual(self._post('query').status_code, 400)

    def test_unknown_step(self) -> None:
        response = self.client.post(
            URL.replace('stepper.gather_metrics', 'other.gather_metrics'),
            json={'field': 'datasource'},
        )
        self.assertEqual(response.status_code, 404)

    def test_integration_not_found(self) -> None:
        self.db.execute.return_value = []
        self.assertEqual(self._post().status_code, 404)

    def test_capability_off(self) -> None:
        self.db.execute.return_value = [
            {
                'integration': _integration(
                    capabilities={'workflow-steps': {'enabled': False}}
                )
            }
        ]
        self.assertEqual(self._post().status_code, 404)

    def test_plugin_error(self) -> None:
        self.choices.side_effect = RuntimeError('boom')
        response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['detail'], {'error': 'plugin_error'})

    def test_bad_plugin_answer(self) -> None:
        self.choices.return_value = [{'value': 1}]
        self.assertEqual(self._post().status_code, 502)

    def test_plugin_timeout(self) -> None:
        async def slow(*_: typing.Any) -> list[base.Choice]:
            await asyncio.sleep(1)
            return []

        self.choices.side_effect = slow
        with mock.patch.object(module, 'TIME_LIMIT_SECONDS', 0.01):
            response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()['detail'], {'error': 'plugin_timeout'}
        )

    def test_needs_both_permissions(self) -> None:
        for held in ({'workflow:write'}, {'integration:read'}):
            self.auth.permissions = held
            self.assertEqual(self._post().status_code, 403, held)
