import json
import uuid

import jsonpatch

from imbi.endpoints.admin import namespaces
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
        result = self.fetch('/admin/namespace', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        print(result.body)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url('/admin/namespace/{}'.format(record['name']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                namespaces.CRUDRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            new_value['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del new_value[field]
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['icon_class'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']), method='PATCH',
            body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        for field in ['created_by', 'last_modified_by']:
            self.assertEqual(
                new_value[field], self.USERNAME[self.ADMIN_ACCESS])
            del new_value[field]
        self.assertDictEqual(new_value, updated)

        # Patch no change
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']), method='PATCH',
            body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']),
            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url('/admin/namespace/{}'.format(record['name']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                namespaces.CRUDRequestHandler.TTL))

        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            new_value['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del new_value[field]
        self.assertDictEqual(new_value, updated)

        # DELETE
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']),
            headers=self.headers)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_create_with_missing_fields(self):
        record = {
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/namespace', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(new_value['name'], record['name'])
        self.assertEqual(new_value['slug'], record['slug'])
        self.assertIsNotNone(new_value['icon_class'])

        # DELETE
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(
            '/admin/namespace/{}'.format(record['name']),
            headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_method_not_implemented(self):
        for method in {'GET', 'DELETE', 'PATCH'}:
            result = self.fetch(
                '/admin/namespace', method=method,
                allow_nonstandard_methods=True,
                headers=self.headers)
            self.assertEqual(result.code, 405)

        url = '/admin/namespace/' + str(uuid.uuid4())
        result = self.fetch(url, method='POST',
                            allow_nonstandard_methods=True,
                            headers=self.headers)
        self.assertEqual(result.code, 405)
