import json
import uuid

import jsonpatch

from imbi.endpoints.admin import project_link_types
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True

    def test_project_link_type_lifecycle(self):
        record = {
            'link_type': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }

        # Create
        result = self.fetch('/admin/project_link_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url(
                    '/admin/project_link_type/{}'.format(
                        record['link_type']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_link_types.CRUDRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['icon_class'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            '/admin/project_link_type/{}'.format(record['link_type']),
            method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, updated)

        # Patch no change
        result = self.fetch(
            '/admin/project_link_type/{}'.format(record['link_type']),
            method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(
            '/admin/project_link_type/{}'.format(record['link_type']),
            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url(
                    '/admin/project_link_type/{}'.format(
                        record['link_type']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project_link_types.CRUDRequestHandler.TTL))

        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, updated)

        # DELETE
        result = self.fetch(
            '/admin/project_link_type/{}'.format(record['link_type']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(
            '/admin/project_link_type/{}'.format(record['link_type']),
            headers=self.headers)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(
            '/admin/project_link_type/{}'.format(record['link_type']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_create_with_missing_fields(self):
        record = {
            'link_type': str(uuid.uuid4())
        }
        result = self.fetch('/admin/project_link_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 400)

    def test_method_not_implemented(self):
        for method in {'GET', 'DELETE', 'PATCH'}:
            result = self.fetch(
                '/admin/project_link_type', method=method,
                allow_nonstandard_methods=True,
                headers=self.headers)
            self.assertEqual(result.code, 405)

        url = '/admin/project_link_type/' + str(uuid.uuid4())
        result = self.fetch(url, method='POST', body='{}',
                            allow_nonstandard_methods=True,
                            headers=self.headers)
        self.assertEqual(result.code, 405)
