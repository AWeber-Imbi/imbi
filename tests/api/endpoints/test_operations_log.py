import datetime
import json
import uuid

import jsonpatch

from imbi.endpoints import operations_log
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.operations_log',
        'v1.projects',
        'v1.project_types',
        'v1.namespaces',
        'v1.environments',
    ]

    def setUp(self):
        super().setUp()
        self.environments = self.create_environments()
        self.environment = self.environments[0]
        self.namespace = self.create_namespace()
        self.project_type = self.create_project_type()
        self.project = self.create_project()

    def create_record(self, **overrides):
        record = {
            'environment': self.environment,
            'project_id': self.project['id'],
            'change_type': 'Upgraded',
            'description': str(uuid.uuid4()),
            'link': str(uuid.uuid4()),
            'notes': str(uuid.uuid4()),
            'ticket_slug': str(uuid.uuid4()),
            'version': str(uuid.uuid4()),
        }
        record.update(overrides)
        result = self.fetch('/operations-log', method='POST', json_body=record)
        self.assertEqual(result.code, 200)
        return json.loads(result.body.decode('utf-8'))

    def assert_records_equal(
        self,
        actual_records,
        expected_records,
    ):
        self.assertEqual(
            [r['id'] for r in actual_records],
            [r['id'] for r in expected_records],
            f'actual: {[r["id"] for r in actual_records]!r}',
        )
        for (actual, expected) in zip(actual_records, expected_records):
            self.assertDictEqual(actual, expected)

    def test_get_static_collection(self):
        records = [self.create_record() for _ in range(10)]

        # page 1
        namespace_id = self.namespace['id']
        result = self.fetch(
            f'/operations-log?limit=4&namespace_id={namespace_id}')
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[6:10]))
        next_link = self.assert_has_link(result, 'next')
        self.assert_no_link(result, 'previous')

        # page 2
        result = self.fetch(next_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[2:6]))
        next_link = self.assert_has_link(result, 'next')
        self.assert_has_link(result, 'previous')

        # page 3
        result = self.fetch(next_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[:2]))
        self.assert_no_link(result, 'next')
        previous_link = self.assert_has_link(result, 'previous')

        # page 2
        result = self.fetch(previous_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[2:6]))
        self.assert_has_link(result, 'next')
        previous_link = self.assert_has_link(result, 'previous')

        # page 1
        result = self.fetch(previous_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[6:]))
        self.assert_has_link(result, 'next')
        self.assert_no_link(result, 'previous')

    def test_get_concurrently_updated_collection(self):
        when = datetime.datetime(2021,
                                 8,
                                 30,
                                 0,
                                 0,
                                 0,
                                 tzinfo=datetime.timezone.utc)
        records = [
            self.create_record(occurred_at=when.replace(
                second=seconds).isoformat()) for seconds in range(6)
        ]

        # page 1
        result = self.fetch('/operations-log?limit=3')
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[3:6]))
        next_link = self.assert_has_link(result, 'next')

        # page 2
        result = self.fetch(next_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 3)
        self.assert_records_equal(response, reversed(records[:3]))
        self.assert_no_link(result, 'next')
        previous_link = self.assert_has_link(result, 'previous')

        # insert record
        record = self.create_record(occurred_at=when.replace(
            second=3).isoformat())
        self.assertEqual(result.code, 200)
        records.insert(4, record)

        # previous page (now page 2/3)
        result = self.fetch(previous_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, reversed(records[3:6]))
        self.assert_has_link(result, 'next')
        previous_link = self.assert_has_link(result, 'previous')

        # previous page (now page 1/3)
        result = self.fetch(previous_link)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assert_records_equal(response, records[6:7])
        self.assert_has_link(result, 'next')
        self.assert_no_link(result, 'previous')

    def test_operations_log_lifecycle(self):
        record = {
            'occurred_at': '2021-08-30T00:00:00+00:00',
            'environment': self.environment,
            'change_type': 'Upgraded',
            'description': str(uuid.uuid4()),
            'link': str(uuid.uuid4()),
            'notes': str(uuid.uuid4()),
            'ticket_slug': str(uuid.uuid4()),
            'version': str(uuid.uuid4()),
        }

        # Create
        result = self.fetch('/operations-log', method='POST', json_body=record)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/operations-log/{}'.format(response['id']))
        self.assert_link_header_equals(result, url)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                operations_log.RecordRequestHandler.TTL))
        record.update(response)
        self.assertDictEqual(response, record)

        # PATCH
        updated = dict(record)
        updated['description'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')
        record.update({
            'description': updated['description'],
        })

        result = self.fetch(url, method='PATCH', body=patch_value)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, url)
        response = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(response, record)

        # Patch no change
        result = self.fetch(url, method='PATCH', body=patch_value)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(url)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                operations_log.RecordRequestHandler.TTL))
        response = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(response, record)

        # Collection
        result = self.fetch('/operations-log')
        self.assertEqual(result.code, 200)
        self.assertListEqual(json.loads(result.body.decode('utf-8')),
                             [dict(record.items())])

        # DELETE
        result = self.fetch(url, method='DELETE')
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(url)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(url, method='DELETE')
        self.assertEqual(result.code, 404)

    def test_create_with_missing_fields(self):
        record = {
            'environment': self.environment,
            'change_type': 'Upgraded',
            'description': 'Upgraded app',
        }
        result = self.fetch('/operations-log', method='POST', json_body=record)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        url = self.get_url('/operations-log/{}'.format(response['id']))
        self.assert_link_header_equals(result, url)
        self.assertEqual(response['environment'], record['environment'])
        self.assertEqual(response['change_type'], record['change_type'])
        self.assertEqual(response['description'], record['description'])

        # DELETE
        result = self.fetch(url, method='DELETE')
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(url)
        self.assertEqual(result.code, 404)

    def test_method_not_implemented(self):
        for method in {'DELETE', 'PATCH'}:
            result = self.fetch('/operations-log', method=method)
            self.assertEqual(result.code, 405)

        url = '/operations-log/' + str(uuid.uuid4())
        result = self.fetch(url, method='POST')
        self.assertEqual(result.code, 405)
