import json
import uuid

import jsonpatch

from imbi.endpoints import project_types
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = ['v1.project_types', 'v1.project_fact_types']

    def setUp(self) -> None:
        super().setUp()
        self.project_type = self.create_project_type()

    def test_project_fact_type_lifecycle(self):
        record = {
            'project_type_id': self.project_type,
            'fact_type': str(uuid.uuid4()),
            'weight': 100
        }

        # Create
        result = self.fetch(
            '/project_fact_types', method='POST',
            body=json.dumps(record).encode('utf-8'), headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        record['id'] = response['id']
        url = self.get_url(
            '/project_fact_types/{}'.format(response['id']))
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_types.AdminCRUDRequestHandler.TTL))
        self.assertEqual(
            response['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del response[field]
        self.assertDictEqual(response, record)

        # PATCH
        updated = dict(record)
        updated['weight'] = 25
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, url)
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
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_types.AdminCRUDRequestHandler.TTL))

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

    def test_create_with_missing_fields(self):
        record = {
            'project_type_id': self.project_type,
            'fact_type': str(uuid.uuid4())
        }
        result = self.fetch(
            '/project_fact_types', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 400)

    def test_method_not_implemented(self):
        for method in {'GET', 'DELETE', 'PATCH'}:
            result = self.fetch(
                '/project_fact_types', method=method,
                allow_nonstandard_methods=True, headers=self.headers)
            self.assertEqual(result.code, 405)

        result = self.fetch(
            '/project_fact_types/99999', method='POST',
            allow_nonstandard_methods=True, headers=self.headers)
        self.assertEqual(result.code, 405)
