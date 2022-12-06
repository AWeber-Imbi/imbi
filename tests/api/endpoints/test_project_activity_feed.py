import datetime
import json

import ietfparse.headers

from tests import base


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.operations_log',
        'v1.projects',
        'v1.project_fact_types',
        'v1.project_types',
        'v1.namespaces',
        'v1.environments',
    ]

    def setUp(self) -> None:
        super().setUp()
        self.environments = self.create_environments()
        self.namespace = self.create_namespace()
        self.project_type = self.create_project_type()
        self.project_fact_type = self.create_project_fact_type(
            data_type='string', fact_type='free-form')
        self.project = self.create_project()

    def update_project_fact(self) -> None:
        result = self.fetch(f'/projects/{self.project["id"]}/facts',
                            method='POST',
                            json_body=[{
                                'fact_type_id': self.project_fact_type['id'],
                                'value': 'foo'
                            }])
        self.assertEqual(result.code, 204)

    def add_operation_log_entry(self, **overrides) -> None:
        body = {
            'change_type': 'Deployed',
            'environment': self.environments[0],
            'project_id': self.project['id'],
            'recorded_by': self.USERNAME[self.ADMIN_ACCESS],
            'recorded_at': now(),
            'notes': '',
        }
        body.update(overrides)
        result = self.fetch('/operations-log', method='POST', json_body=body)
        self.assertEqual(result.code, 200)

    def test_project_only_feed(self):
        self.update_project_fact()

        result = self.fetch(f'/projects/{self.project["id"]}/feed')
        self.assertEqual(result.code, 200)
        for link in ietfparse.headers.parse_link(result.headers['Link']):
            self.assertNotEqual(dict(link.parameters)['rel'], 'next')

        body = json.loads(result.body.decode('utf-8'))
        self.assertEqual(len(body), 2)
        self.assertEqual([entry['what'] for entry in body],
                         ['updated fact', 'created'])
        self.assertGreater(
            datetime.datetime.fromisoformat(body[0]['when']),
            datetime.datetime.fromisoformat(body[1]['when']),
        )

    def test_pagination(self):
        notes = []
        for index in range(10):
            notes.append(str(index))
            self.add_operation_log_entry(notes=notes[-1])
        notes.reverse()

        remaining = len(notes) + 1  # includes project created entry
        url = f'/projects/{self.project["id"]}/feed?limit=3'
        while url is not None:
            result = self.fetch(url)
            self.assertEqual(result.code, 200)

            url = None
            for link in ietfparse.headers.parse_link(result.headers['Link']):
                params = dict(link.parameters)
                if params['rel'] == 'next':
                    url = link.target
                    break

            body = json.loads(result.body.decode('utf-8'))
            self.assertEqual(len(body), min(3, remaining))
            received_notes = [
                entry['notes'] for entry in body
                if entry['type'] == 'OperationsLogEntry'
            ]
            self.assertEqual(notes[:len(received_notes)], received_notes)
            notes = notes[len(received_notes):]
            remaining -= len(body)

        self.assertEqual(notes, [])

    def test_mixed_activity_feed(self):
        for index in range(10):
            if index % 2 == 0:
                self.add_operation_log_entry()
            else:
                self.add_operation_log_entry(project_id=None)

        result = self.fetch(f'/projects/{self.project["id"]}/facts',
                            method='POST',
                            json_body=[{
                                'fact_type_id': self.project_fact_type['id'],
                                'value': 'foo'
                            }])
        self.assertEqual(result.code, 204)

        result = self.fetch(f'/projects/{self.project["id"]}/feed?limit=20')
        self.assertEqual(result.code, 200)
        body = json.loads(result.body.decode('utf-8'))
        # project created, 5 operation logs, and project updated
        self.assertEqual(len(body), 1 + 5 + 1)
