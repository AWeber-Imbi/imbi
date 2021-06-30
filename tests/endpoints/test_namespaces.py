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
            field: namespaces.CollectionRequestHandler.DEFAULTS.get(
                field, None)
            for field in namespaces.CollectionRequestHandler.FIELDS
            if field != namespaces.CollectionRequestHandler.ID_KEY
        }
        record.update({
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'icon_class': 'fas fa-blind',
        })

        # Create
        result = self.fetch(
            '/namespaces', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/namespaces/{}'.format(response['id']))
        record.update({
            'id': response['id'],
            'created_by': self.USERNAME[self.ADMIN_ACCESS],
            'last_modified_by': None
        })
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                namespaces.RecordRequestHandler.TTL))
        self.assertDictEqual(response, record)

        # PATCH
        updated = dict(record)
        updated['icon_class'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')
        record.update({
            'icon_class': updated['icon_class'],
            'last_modified_by': self.USERNAME[self.ADMIN_ACCESS]
        })

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, url)
        response = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(response, record)

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
                namespaces.RecordRequestHandler.TTL))
        response = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(response, record)

        # Collection
        result = self.fetch('/namespaces', headers=self.headers)
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
        for method in {'DELETE', 'PATCH'}:
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
