from __future__ import annotations

import http
import json
import uuid

import yarl
from tornado import httpclient

from imbi.endpoints.integrations import automations
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):
    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.integrations',
        'v1.project_types',
    ]

    def setUp(self) -> None:
        super().setUp()
        self.project_type = self.create_project_type()
        self.project_fact_type = self.create_project_fact_type()

        self.integration_name = 'some-app'
        rsp = self.fetch('/integrations',
                         method='POST',
                         json_body={
                             'name': self.integration_name,
                             'api_endpoint': 'https://integration.example.com',
                             'api_secret': None,
                         })
        self.assertEqual(http.HTTPStatus.OK, rsp.code)
        self.automations_url = (yarl.URL('/integrations') /
                                self.integration_name / 'automations')

    def create_automation(self, **overrides: object) -> automations.Automation:
        body: dict[str, object] = {
            'name': str(uuid.uuid4()),
            'categories': ['create-project'],
            'applies_to': [self.project_type['id']]
        }
        body.update(overrides)
        rsp = self.fetch(str(self.automations_url),
                         method='POST',
                         json_body=body)
        self.assertEqual(http.HTTPStatus.OK, rsp.code)
        return self._parse_automation(rsp)

    def _parse_automation(
            self, response: httpclient.HTTPResponse) -> automations.Automation:
        self.assertEqual(
            'application/json',
            response.headers.get('content-type',
                                 'binary/octet-stream').partition(';')[0])
        return automations.Automation.model_validate(
            json.loads(response.body.decode('utf-8')))

    def test_with_no_automations(self) -> None:
        rsp = self.fetch(str(self.automations_url))
        self.assertEqual(http.HTTPStatus.OK, rsp.code)

        rsp = self.fetch(str(self.automations_url / str(uuid.uuid4())))
        self.assertEqual(http.HTTPStatus.NOT_FOUND, rsp.code)

    def test_creating_automation(self) -> None:
        automation = self.create_automation(name='First automation')
        self.assertEqual('First automation', automation.name)
        self.assertEqual([self.project_type['slug']], automation.applies_to)
        self.assertEqual('test', automation.created_by)
        self.assertIsNotNone(automation.created_at)
        self.assertIsNone(automation.last_modified_by)
        self.assertIsNone(automation.last_modified_at)

    def test_creating_automation_with_project_type_slug(self) -> None:
        automation = self.create_automation(
            applies_to=[self.project_type['slug']])
        self.assertEqual([self.project_type['slug']], automation.applies_to)

    def test_retrieving_automation(self) -> None:
        automation = self.create_automation()

        rsp = self.fetch(str(self.automations_url))
        self.assertEqual(http.HTTPStatus.OK, rsp.code)
        self.assertEqual(
            'application/json',
            rsp.headers.get('content-type',
                            'binary/octet-stream').partition(';')[0])
        body = json.loads(rsp.body.decode('utf-8'))
        self.assertEqual(1, len(body))
        self.assertEqual(automation,
                         automations.Automation.model_validate(body[0]))

        for id_value in (automation.id, automation.slug, automation.name):
            url = self.automations_url / str(id_value)
            rsp = self.fetch(str(url))
            self.assertEqual(http.HTTPStatus.OK, rsp.code)
            self.assertEqual(
                'application/json',
                rsp.headers.get('content-type',
                                'binary/octet-stream').partition(';')[0])
            retrieved = automations.Automation.model_validate(
                json.loads(rsp.body.decode('utf-8')))
            self.assertEqual(retrieved, automation)

    def test_deleting_automations(self) -> None:
        rsp = self.fetch(str(self.automations_url / str(uuid.uuid4())),
                         method='DELETE')
        self.assertEqual(http.HTTPStatus.NOT_FOUND, rsp.code)

        for attr_name in ['id', 'slug', 'name']:
            automation = self.create_automation()
            url = self.automations_url / str(getattr(automation, attr_name))
            rsp = self.fetch(str(url), method='DELETE')
            self.assertEqual(http.HTTPStatus.NO_CONTENT, rsp.code)

            rsp = self.fetch(str(url))
            self.assertEqual(http.HTTPStatus.NOT_FOUND, rsp.code)

    def test_updating_automations(self) -> None:
        rsp = self.fetch(str(self.automations_url / str(uuid.uuid4())),
                         method='PATCH',
                         json_body=[])
        self.assertEqual(http.HTTPStatus.NOT_FOUND, rsp.code)

        automation = self.create_automation()
        patch_url = str(self.automations_url / automation.slug)

        # update the name and make sure that we can fetch the
        # automation by the new name, original slug, and original id
        patch = [{'op': 'replace', 'path': '/name', 'value': 'Real name'}]
        rsp = self.fetch(patch_url, method='PATCH', json_body=patch)
        self.assertEqual(http.HTTPStatus.OK, rsp.code)
        patched = self._parse_automation(rsp)
        self.assertEqual(automation.id, patched.id)
        self.assertEqual('Real name', patched.name)
        self.assertIsNotNone(patched.last_modified_at)
        self.assertEqual('test', patched.last_modified_by)

        rsp = self.fetch(str(self.automations_url / automation.name))
        self.assertEqual(http.HTTPStatus.NOT_FOUND, rsp.code)

        rsp = self.fetch(str(self.automations_url / automation.slug))
        self.assertEqual(http.HTTPStatus.OK, rsp.code)

        rsp = self.fetch(str(self.automations_url / patched.name))
        self.assertEqual(http.HTTPStatus.OK, rsp.code)

        # update it with the same name... should get a 304
        rsp = self.fetch(patch_url, method='PATCH', json_body=patch)
        self.assertEqual(http.HTTPStatus.NOT_MODIFIED, rsp.code)
