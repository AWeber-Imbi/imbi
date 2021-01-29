import json
import uuid

import jsonpatch

from imbi.endpoints import groups
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True

    def test_group_lifecycle(self):
        record = {
            'name': str(uuid.uuid4()),
            'group_type': 'internal',
            'external_id': None,
            'permissions': ['admin']
        }

        # Create
        result = self.fetch(
            '/groups', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        url = self.get_url('/groups/{}'.format(record['name']))
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                groups.AdminCRUDRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            new_value['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del new_value[field]
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['group_type'] = 'ldap'
        updated['external_id'] = str(uuid.uuid4())
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
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                groups.AdminCRUDRequestHandler.TTL))
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
            'name': str(uuid.uuid4()),
            'group_type': 'internal'
        }
        result = self.fetch(
            '/groups', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(new_value['name'], record['name'])
        self.assertEqual(new_value['group_type'], 'internal')
        self.assertIsNone(new_value['external_id'])
        self.assertListEqual(new_value['permissions'], [])

    def test_method_not_implemented(self):
        for method in {'GET', 'DELETE', 'PATCH'}:
            result = self.fetch(
                '/groups', method=method, headers=self.headers,
                allow_nonstandard_methods=True)
            self.assertEqual(result.code, 405)
        url = '/groups/' + str(uuid.uuid4())
        result = self.fetch(
            url, method='POST', allow_nonstandard_methods=True,
            headers=self.headers)
        self.assertEqual(result.code, 405)
