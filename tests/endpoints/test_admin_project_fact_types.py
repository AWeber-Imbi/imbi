import json
import uuid

import jsonpatch

from imbi.endpoints.admin import project_types
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = ['v1.project_types', 'v1.project_fact_types']

    def setUp(self) -> None:
        super().setUp()
        self.project_type = self.create_project_type()

    def tearDown(self) -> None:
        self.fetch('/admin/project_type/{}'.format(self.project_type),
                   method='DELETE',
                   headers=self.headers)
        super().tearDown()

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

    def test_project_fact_type_lifecycle(self):
        record = {
            'id': str(uuid.uuid4()),
            'project_type': self.project_type,
            'name': str(uuid.uuid4()),
            'weight': 100
        }

        # Create
        result = self.fetch('/admin/project_fact_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url(
                    '/admin/project_fact_type/{}'.format(record['id']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_types.CRUDRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['weight'] = 25
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            '/admin/project_fact_type/{}'.format(record['id']),
            method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, updated)

        # Patch no change
        result = self.fetch(
            '/admin/project_fact_type/{}'.format(record['id']),
            method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(
            '/admin/project_fact_type/{}'.format(record['id']),
            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url(
                    '/admin/project_fact_type/{}'.format(record['id']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_types.CRUDRequestHandler.TTL))

        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, updated)

        # DELETE
        result = self.fetch(
            '/admin/project_fact_type/{}'.format(record['id']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(
            '/admin/project_fact_type/{}'.format(record['id']),
            headers=self.headers)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(
            '/admin/project_fact_type/{}'.format(record['id']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_create_with_missing_fields(self):
        record = {
            'id': str(uuid.uuid4()),
            'project_type': self.project_type,
            'name': str(uuid.uuid4())
        }
        result = self.fetch('/admin/project_fact_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 400)

    def test_method_not_implemented(self):
        for method in {'GET', 'DELETE', 'PATCH'}:
            result = self.fetch(
                '/admin/project_fact_type', method=method,
                allow_nonstandard_methods=True,
                headers=self.headers)
            self.assertEqual(result.code, 405)

        url = '/admin/project_fact_type/' + str(uuid.uuid4())
        result = self.fetch(url, method='POST',
                            allow_nonstandard_methods=True,
                            headers=self.headers)
        self.assertEqual(result.code, 405)
