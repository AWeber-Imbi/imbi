import json
import uuid

import jsonpatch

from imbi.endpoints import cookie_cutters
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.cookie_cutters',
        'v1.project_types'
    ]

    def setUp(self):
        super().setUp()
        self.project_type = self.create_project_type()

    def test_cookie_cutter_lifecycle(self):
        record = {
            'name': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'type': 'project',
            'project_type_id': self.project_type,
            'url': 'http://{}/{}.git'.format(uuid.uuid4(), uuid.uuid4())
        }

        # Create
        result = self.fetch(
            '/cookie-cutters', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        url = self.get_url('/cookie-cutters/{}'.format(record['name']))
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                cookie_cutters.CollectionRequestHandler.TTL))
        record.update({
            'created_by': self.USERNAME[self.ADMIN_ACCESS],
            'last_modified_by': None
        })
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['description'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')
        record.update({
            'description': updated['description'],
            'last_modified_by': self.USERNAME[self.ADMIN_ACCESS]
        })

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, record)

        # Patch no change
        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                cookie_cutters.RecordRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, record)

        # Collection
        result = self.fetch('/cookie-cutters', headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertListEqual(
            json.loads(result.body.decode('utf-8')),
            [{k: v for k, v in record.items()
              if k not in ['created_by', 'last_modified_by']}])

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
            'name': str(uuid.uuid4()),
            'type': 'dashboard',
            'project_type_id': self.project_type,
            'url': 'http://{}/{}.git'.format(uuid.uuid4(), uuid.uuid4())
        }
        result = self.fetch(
            '/cookie-cutters', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(new_value['name'], record['name'])
        self.assertIsNone(new_value['description'])

    def test_method_not_implemented(self):
        for method in {'DELETE', 'PATCH'}:
            result = self.fetch(
                '/cookie-cutters', method=method, headers=self.headers,
                allow_nonstandard_methods=True)
            self.assertEqual(result.code, 405)
        result = self.fetch(
            '/cookie-cutters/' + str(uuid.uuid4()), method='POST',
            allow_nonstandard_methods=True, headers=self.headers)
        self.assertEqual(result.code, 405)
