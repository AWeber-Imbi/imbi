import http.client
import unittest.mock
import uuid

import sprockets.mixins.http
from tornado import httputil

from imbi import errors, models, version
from imbi.clients import pagerduty
from tests import base


class PagerDutyClientTestCase(base.TestCaseWithReset):
    ADMIN_ACCESS = True
    TRUNCATE_TABLES = ['v1.integrations']

    def setUp(self) -> None:
        super().setUp()
        self._patcher = unittest.mock.patch.object(
            pagerduty._PagerDutyClient,
            'http_fetch',
            new_callable=unittest.mock.AsyncMock,
            create=True,
        )
        self.http_fetch_mock = self._patcher.start()
        self.integration = self.create_integration(
            api_endpoint='https://example.com/pagerduty/api',
            api_secret='my-secret')

        config = self.settings.setdefault('automations', {})
        config['pagerduty'] = {'enabled': True}

        self.client: pagerduty._PagerDutyClient = self.run_until_complete(
            pagerduty.create_client(self.app, self.integration['name']))

    def tearDown(self) -> None:
        self._patcher.stop()
        super().tearDown()

    @staticmethod
    def create_successful_response(body=None):
        if body is None:
            body = {
                'service': {
                    'html_url': 'https://example.com/html_url',
                    'id': str(uuid.uuid4()),
                    'self': 'https://example.com/self',
                }
            }
        response = unittest.mock.Mock()
        response.ok = True
        response.code = http.HTTPStatus.CREATED.value
        response.body = body
        return response

    @staticmethod
    def create_error_response() -> sprockets.mixins.http.HTTPResponse:
        response = unittest.mock.Mock()
        response.ok = False
        response.code = http.HTTPStatus.INTERNAL_SERVER_ERROR.value
        response.history = [unittest.mock.Mock()]
        response.history[0].effective_url = 'https://example.com/effective-url'
        return response


class PagerDutyCreateClientTests(base.TestCaseWithReset):
    ADMIN_ACCESS = True
    TRUNCATE_TABLES = ['v1.integrations', 'v1.namespaces']

    def setUp(self) -> None:
        super().setUp()
        self.integration = self.create_integration(api_secret='my-secret')
        config = self.settings.setdefault('automations', {})
        config['pagerduty'] = {'enabled': True}

    def test_correctly_configured(self) -> None:
        self.run_until_complete(
            pagerduty.create_client(self.app, self.integration['name']))

    def test_missing_configuration(self) -> None:
        del self.settings['automations']['pagerduty']
        with self.assertRaises(errors.ClientUnavailableError):
            self.run_until_complete(
                pagerduty.create_client(self.app, self.integration['name']))

    def test_pagerduty_disabled(self) -> None:
        self.settings['automations']['pagerduty']['enabled'] = False
        with self.assertRaises(errors.ClientUnavailableError):
            self.run_until_complete(
                pagerduty.create_client(self.app, self.integration['name']))

    def test_with_incorrect_integration_name(self) -> None:
        with self.assertRaises(errors.ClientUnavailableError):
            self.run_until_complete(
                pagerduty.create_client(self.app, str(uuid.uuid4())))

    def test_with_missing_api_secret(self) -> None:
        integration = self.create_integration()
        with self.assertRaises(errors.ClientUnavailableError):
            self.run_until_complete(
                pagerduty.create_client(self.app, integration['name']))


class PagerDutyProjectCreationTests(PagerDutyClientTestCase):
    TRUNCATE_TABLES = [
        'v1.environments', 'v1.integrations', 'v1.namespaces', 'v1.projects',
        'v1.project_types'
    ]

    def setUp(self) -> None:
        super().setUp()
        project = self.create_project()
        self.disabled_project: models.Project = self.run_until_complete(
            models.project(project['id'], self.app))

        enabled_namespace = self.create_namespace(pagerduty_policy='my-policy')
        project = self.create_project(namespace_id=enabled_namespace['id'])
        self.enabled_project: models.Project = self.run_until_complete(
            models.project(project['id'], self.app))

    def test_calling_with_namespace_policy(self) -> None:
        self.http_fetch_mock.return_value = self.create_successful_response()
        self.run_until_complete(
            self.client.create_service(self.enabled_project))
        self.http_fetch_mock.assert_awaited_once_with(
            'https://example.com/pagerduty/api/services',
            method='POST',
            body={
                'name': self.enabled_project.slug,
                'description': self.enabled_project.description,
                'escalation_policy': {
                    'id': self.enabled_project.namespace.pagerduty_policy,
                    'type': 'escalation_policy_reference'
                }
            },
            request_headers=unittest.mock.ANY,
            content_type='application/json',
            user_agent=f'imbi/{version} (PagerDutyClient)')
        _, kwargs = self.http_fetch_mock.await_args
        request_headers = httputil.HTTPHeaders(kwargs['request_headers'])
        self.assertEqual('Token token=my-secret',
                         request_headers['Authorization'])

    def test_calling_without_namespace_policy(self) -> None:
        with self.assertRaises(errors.InternalServerError):
            self.run_until_complete(
                self.client.create_service(self.disabled_project))
        self.http_fetch_mock.assert_not_awaited()

    def test_empty_description_is_omitted(self) -> None:
        self.http_fetch_mock.return_value = self.create_successful_response()
        self.enabled_project.description = None
        self.run_until_complete(
            self.client.create_service(self.enabled_project))
        self.http_fetch_mock.assert_awaited_once_with(
            'https://example.com/pagerduty/api/services',
            method='POST',
            body={
                'name': self.enabled_project.slug,
                'escalation_policy': {
                    'id': self.enabled_project.namespace.pagerduty_policy,
                    'type': 'escalation_policy_reference'
                }
            },
            request_headers=unittest.mock.ANY,
            content_type='application/json',
            user_agent=f'imbi/{version} (PagerDutyClient)')

    def test_unexpected_response_handling(self) -> None:
        self.http_fetch_mock.return_value = self.create_successful_response({})
        with self.assertRaises(errors.InternalServerError):
            self.run_until_complete(
                self.client.create_service(self.enabled_project))

    def test_pagerduty_api_failure(self) -> None:
        response = unittest.mock.Mock()
        response.ok = False
        response.code = http.HTTPStatus.INTERNAL_SERVER_ERROR.value
        response.history = [
            unittest.mock.Mock(effective_url='https://example.com')
        ]
        self.http_fetch_mock.return_value = response

        with self.assertRaises(errors.InternalServerError):
            self.run_until_complete(
                self.client.create_service(self.enabled_project))


class PagerDutyProjectDeletionTests(PagerDutyClientTestCase):
    def test_removing_service(self) -> None:
        self.run_until_complete(self.client.remove_service('some-service-id'))
        self.http_fetch_mock.assert_awaited_once_with(
            'https://example.com/pagerduty/api/services/some-service-id',
            method='DELETE',
            request_headers=unittest.mock.ANY,
            user_agent=f'imbi/{version} (PagerDutyClient)')
        _, kwargs = self.http_fetch_mock.await_args
        request_headers = httputil.HTTPHeaders(kwargs['request_headers'])
        self.assertEqual('Token token=my-secret',
                         request_headers['Authorization'])


class PagerDutyCreateIntegrationTests(PagerDutyClientTestCase):
    TRUNCATE_TABLES = [
        'v1.environments', 'v1.integrations', 'v1.namespaces', 'v1.projects',
        'v1.project_secrets', 'v1.project_types'
    ]

    def setUp(self) -> None:
        super().setUp()
        self.namespace = self.create_namespace(pagerduty_policy='my-policy')
        project = self.create_project()
        self.project: models.Project = self.run_until_complete(
            models.project(project['id'], self.app))
        self.service = pagerduty.ServiceInfo(
            id='SERVICE',
            html_url='https://example.com/html_url',
            self='https://example.com/self')

    def test_creating_integration(self) -> None:
        self.http_fetch_mock.return_value = self.create_successful_response({
            'integration': {
                'id': 'INTEGRATION',
                'name': 'my-hook',
                'type': 'whatever',
                'self': 'https://example.com/self',
                'html_url': 'https://example.com/html_url',
                'integration_key': 'super secret key',
            }
        })
        integration = self.run_until_complete(
            self.client.create_inbound_api_integration('my-hook',
                                                       self.service))
        self.http_fetch_mock.assert_awaited_once_with(
            'https://example.com/pagerduty/api/services/SERVICE/integrations',
            method='POST',
            body={
                'integration': {
                    'name': 'my-hook',
                    'type': 'generic_events_api_inbound_integration',
                }
            },
            content_type='application/json',
            request_headers=unittest.mock.ANY,
            user_agent=f'imbi/{version} (PagerDutyClient)',
        )
        self.assertEqual('INTEGRATION', integration.id)
        self.assertEqual('super secret key', integration.integration_key)

    def test_api_failure(self) -> None:
        self.http_fetch_mock.return_value = self.create_error_response()
        with self.assertRaises(errors.InternalServerError):
            self.run_until_complete(
                self.client.create_inbound_api_integration(
                    'my-hook', self.service))
