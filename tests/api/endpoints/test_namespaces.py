import json
import uuid

import jsonpatch

from imbi.endpoints import namespaces
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = ['v1.namespaces']

    def test_namespace_lifecycle(self):
        record = {
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'icon_class': 'fas fa-blind',
            'maintained_by': []
        }

        # Create
        result = self.fetch(
            '/namespaces', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/namespaces/{}'.format(response['id']))
        record['id'] = response['id']
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                namespaces.AdminCRUDRequestHandler.TTL))
        self.assertEqual(
            response['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del response[field]
        self.assertDictEqual(response, record)

        # PATCH
        updated = dict(record)
        updated['icon_class'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, url)
        response = json.loads(result.body.decode('utf-8'))
        for field in ['created_by', 'last_modified_by']:
            self.assertEqual(
                response[field], self.USERNAME[self.ADMIN_ACCESS])
            del response[field]
        self.assertDictEqual(response, updated)

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
                namespaces.AdminCRUDRequestHandler.TTL))

        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            response['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del response[field]
        self.assertDictEqual(response, updated)

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
            'slug': str(uuid.uuid4().hex),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/namespaces', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/namespaces/{}'.format(response['id']))
        self.assert_link_header_equals(result, url)
        self.assertEqual(response['name'], record['name'])
        self.assertEqual(response['slug'], record['slug'])
        self.assertIsNotNone(response['icon_class'])

        # DELETE
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_method_not_implemented(self):
        for method in {'GET', 'DELETE', 'PATCH'}:
            result = self.fetch(
                '/namespaces', method=method,
                allow_nonstandard_methods=True,
                headers=self.headers)
            self.assertEqual(result.code, 405)

        url = '/namespaces/' + str(uuid.uuid4())
        result = self.fetch(url, method='POST',
                            allow_nonstandard_methods=True,
                            headers=self.headers)
        self.assertEqual(result.code, 405)
