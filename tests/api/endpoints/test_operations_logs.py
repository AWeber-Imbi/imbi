import json
import uuid

import jsonpatch

from imbi.endpoints import operations_logs
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.operations_log',
        'v1.environments',
    ]

    def setUp(self):
        super().setUp()
        self.environment = self.create_environment()

    def test_operations_log_lifecycle(self):
        record = {
            'recorded_by': self.USERNAME[self.ADMIN_ACCESS],
            'recorded_at': '2021-08-30T00:00:00+00:00',
            'environment': self.environment,
            'change_type': 'Upgraded',
            'description': str(uuid.uuid4()),
            'link': str(uuid.uuid4()),
            'notes': str(uuid.uuid4()),
            'ticket_slug': str(uuid.uuid4()),
            'version': str(uuid.uuid4()),
        }

        # Create
        result = self.fetch(
            '/operations-log', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/operations-log/{}'.format(response['id']))
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                operations_logs.RecordRequestHandler.TTL))
        record.update({
            'id': response['id'],
            'completed_at': response['completed_at'],
            'project_id': response['project_id'],
        })
        self.assertDictEqual(response, record)

        # PATCH
        updated = dict(record)
        updated['description'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')
        record.update({
            'description': updated['description'],
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
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                operations_logs.RecordRequestHandler.TTL))
        response = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(response, record)

        # Collection
        result = self.fetch('/operations-log', headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertListEqual(
            json.loads(result.body.decode('utf-8')),
            [{k: v for k, v in record.items()}])

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
            'recorded_by': self.USERNAME[self.ADMIN_ACCESS],
            'recorded_at': '2021-08-30T00:00:00+00:00',
            'environment': self.environment,
            'change_type': 'Upgraded',
        }
        result = self.fetch('/operations-log', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/operations-log/{}'.format(response['id']))
        self.assert_link_header_equals(result, url)
        self.assertEqual(response['environment'], record['environment'])
        self.assertEqual(response['change_type'], record['change_type'])

        # DELETE
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_method_not_implemented(self):
        for method in {'DELETE', 'PATCH'}:
            result = self.fetch(
                '/operations-log', method=method,
                allow_nonstandard_methods=True,
                headers=self.headers)
            self.assertEqual(result.code, 405)

        url = '/operations-log/' + str(uuid.uuid4())
        result = self.fetch(url, method='POST',
                            allow_nonstandard_methods=True,
                            headers=self.headers)
        self.assertEqual(result.code, 405)
