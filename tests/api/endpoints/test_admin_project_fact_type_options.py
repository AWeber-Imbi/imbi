import json
import uuid

import jsonpatch

from imbi.endpoints.admin import project_types
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.project_types',
        'v1.project_fact_types',
        'v1.project_fact_type_options'
    ]

    def setUp(self) -> None:
        super().setUp()
        self.project_type = self.create_project_type()
        self.fact_type = self.create_project_fact_type()

    def create_project_type(self) -> str:
        record = {
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/project_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def create_project_fact_type(self):
        record = {
            'project_type': self.project_type,
            'fact_type': str(uuid.uuid4()),
            'weight': 100
        }

        # Create
        result = self.fetch('/admin/project_fact_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['fact_type']

    def test_project_fact_type_option_lifecycle(self):
        record = {
            'project_type': self.project_type,
            'fact_type': self.fact_type,
            'value': str(uuid.uuid4()),
            'score': 50
        }

        # Create
        result = self.fetch(
            '/admin/project_fact_type_option',
            method='POST', body=json.dumps(record).encode('utf-8'),
            headers=self.headers)

        url = self.get_url('/admin/project_fact_type_option/{}/{}/{}'.format(
            self.project_type, self.fact_type, record['value']))

        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(url))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_types.CRUDRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            new_value['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del new_value[field]
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['score'] = 25
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        for field in ['created_by', 'last_modified_by']:
            self.assertEqual(
                new_value[field], self.USERNAME[self.ADMIN_ACCESS])
            del new_value[field]
        self.assertDictEqual(new_value, updated)

        # Patch no change
        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(url))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_types.CRUDRequestHandler.TTL))

        new_value = json.loads(result.body.decode('utf-8'))
        for field in ['created_by', 'last_modified_by']:
            self.assertEqual(
                new_value[field], self.USERNAME[self.ADMIN_ACCESS])
            del new_value[field]
        self.assertDictEqual(new_value, updated)

        # DELETE
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 404)
