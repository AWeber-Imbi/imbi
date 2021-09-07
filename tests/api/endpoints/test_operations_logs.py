import json
import uuid

import jsonpatch
from ietfparse import headers

from imbi.endpoints import operations_logs
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

    def test_get_static_collection(self):
        records = []
        for i in range(10):
            record = {
                'recorded_by': self.USERNAME[self.ADMIN_ACCESS],
                'recorded_at': '2021-08-30T00:00:00+00:00',
                'environment': self.environment,
                'project_id': self.project['id'],
                'change_type': 'Upgraded',
                'description': str(uuid.uuid4()),
                'link': str(uuid.uuid4()),
                'notes': str(uuid.uuid4()),
                'ticket_slug': str(uuid.uuid4()),
                'version': str(uuid.uuid4()),
            }
            records.append(record)
            result = self.fetch(
                '/operations-log', method='POST', headers=self.headers,
                body=json.dumps(record).encode('utf-8'))
            self.assertEqual(result.code, 200)
            records[i]['id'] = json.loads(result.body.decode('utf-8'))['id']
            records[i]['completed_at'] = None

        # page 1
        namespace_id = self.namespace['id']
        result = self.fetch(
            f'/operations-log?limit=4&namespace_id={namespace_id}',
            headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 4)
        for i in range(4):
            self.assertDictEqual(response[i], records[9 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link = None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            self.assertNotEqual(link_rel, 'previous')
            if link_rel == 'next':
                next_link = header.target
        self.assertIsNotNone(next_link)

        # page 2
        result = self.fetch(next_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 4)
        for i in range(4):
            self.assertDictEqual(response[i], records[5 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link, previous_link = None, None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            if link_rel == 'next':
                next_link = header.target
            elif link_rel == 'previous':
                previous_link = header.target
        self.assertIsNotNone(next_link)
        self.assertIsNotNone(previous_link)

        # page 3
        result = self.fetch(next_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 2)
        for i in range(2):
            self.assertDictEqual(response[i], records[1 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link, previous_link = None, None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            self.assertNotEqual(link_rel, 'next')
            if link_rel == 'previous':
                previous_link = header.target
        self.assertIsNotNone(previous_link)

        # page 2
        result = self.fetch(previous_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 4)
        for i in range(4):
            self.assertDictEqual(response[i], records[5 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link, previous_link = None, None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            if link_rel == 'next':
                next_link = header.target
            elif link_rel == 'previous':
                previous_link = header.target
        self.assertIsNotNone(next_link)
        self.assertIsNotNone(previous_link)

        # page 1
        result = self.fetch(previous_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 4)
        for i in range(4):
            self.assertDictEqual(response[i], records[9 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link = None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            self.assertNotEqual(link_rel, 'previous')
            if link_rel == 'next':
                next_link = header.target
        self.assertIsNotNone(next_link)

    def test_get_concurrently_updated_collection(self):
        records = []
        for i in range(6):
            record = {
                'recorded_by': self.USERNAME[self.ADMIN_ACCESS],
                'recorded_at': f'2021-08-30T00:00:0{i}+00:00',
                'environment': self.environment,
                'project_id': self.project['id'],
                'change_type': 'Upgraded',
                'description': str(uuid.uuid4()),
                'link': str(uuid.uuid4()),
                'notes': str(uuid.uuid4()),
                'ticket_slug': str(uuid.uuid4()),
                'version': str(uuid.uuid4()),
            }
            records.append(record)
            result = self.fetch(
                '/operations-log', method='POST', headers=self.headers,
                body=json.dumps(record).encode('utf-8'))
            self.assertEqual(result.code, 200)
            records[i]['id'] = json.loads(result.body.decode('utf-8'))['id']
            records[i]['completed_at'] = None

        # page 1
        result = self.fetch('/operations-log?limit=3', headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 3)
        for i in range(3):
            self.assertDictEqual(response[i], records[5 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link = None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            self.assertNotEqual(link_rel, 'previous')
            if link_rel == 'next':
                next_link = header.target
        self.assertIsNotNone(next_link)

        # page 2
        result = self.fetch(next_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 3)
        for i in range(3):
            self.assertDictEqual(response[i], records[2 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link, previous_link = None, None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            self.assertNotEqual(link_rel, 'next')
            if link_rel == 'previous':
                previous_link = header.target
        self.assertIsNotNone(previous_link)

        # insert record
        record = {
                'recorded_by': self.USERNAME[self.ADMIN_ACCESS],
                'recorded_at': f'2021-08-30T00:00:03+00:00',
                'environment': self.environment,
                'project_id': self.project['id'],
                'change_type': 'Upgraded',
                'description': str(uuid.uuid4()),
                'link': str(uuid.uuid4()),
                'notes': str(uuid.uuid4()),
                'ticket_slug': str(uuid.uuid4()),
                'version': str(uuid.uuid4()),
            }
        result = self.fetch(
            '/operations-log', method='POST', headers=self.headers,
            body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        record['id'] = json.loads(result.body.decode('utf-8'))['id']
        record['completed_at'] = None
        records.insert(4, record)

        # previous page (now page 2/3)
        result = self.fetch(previous_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 3)
        for i in range(3):
            self.assertDictEqual(response[i], records[5 - i])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link, previous_link = None, None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            if link_rel == 'next':
                next_link = header.target
            elif link_rel == 'previous':
                previous_link = header.target
        self.assertIsNotNone(next_link)
        self.assertIsNotNone(previous_link)

        # previous page (now page 1/3)
        result = self.fetch(previous_link, headers=self.headers)
        self.assertEqual(result.code, 200)
        response = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(response), 1)
        self.assertDictEqual(response[0], records[6])
        link_headers = headers.parse_link(result.headers['Link'])
        next_link, previous_link = None, None
        for header in link_headers:
            link_rel = header.parameters[0][1]
            self.assertNotEqual(link_rel, 'previous')
            if link_rel == 'next':
                next_link = header.target
        self.assertIsNotNone(next_link)

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
