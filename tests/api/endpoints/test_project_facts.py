import datetime
import json
import math
import time

from tests import base


class ProjectFactTests(base.TestCaseWithReset):
    TRUNCATE_TABLES = ['v1.projects', 'v1.project_fact_types']

    def setUp(self) -> None:
        super().setUp()
        self.project = self.create_project()

    def test_valid_fact_values(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        boolean_fact = self.create_project_fact_type(data_type='boolean')
        date_fact = self.create_project_fact_type(data_type='date')
        decimal_fact = self.create_project_fact_type(data_type='decimal')
        integer_fact = self.create_project_fact_type(data_type='integer')
        timestamp_fact = self.create_project_fact_type(data_type='timestamp')
        facts = [
            {'fact_type_id': boolean_fact['id'], 'value': 'yes'},
            {'fact_type_id': date_fact['id'], 'value': now.date().isoformat()},
            {'fact_type_id': decimal_fact['id'], 'value': math.pi},
            {'fact_type_id': integer_fact['id'], 'value': 42},
            {'fact_type_id': timestamp_fact['id'], 'value': now.isoformat()},
        ]
        result = self.fetch(
            f'/projects/{self.project["id"]}/facts',
            method='POST',
            body=json.dumps(facts).encode('utf-8'),
            headers=self.headers)
        self.assertEqual(204, result.code)

        result = self.fetch(f'/projects/{self.project["id"]}/facts',
                            headers=self.headers)
        self.assertEqual(200, result.code)

        data = json.loads(result.body)
        self.assertDictEqual(
            {
                boolean_fact['id']: True,
                date_fact['id']: now.date().isoformat(),
                decimal_fact['id']: float(math.pi),
                integer_fact['id']: 42,
                timestamp_fact['id']: now.isoformat(),
            },
            {fact['fact_type_id']: fact['value'] for fact in data})

    def verify_expectations(self, data_type: str, values: dict) -> None:
        fact_type = self.create_project_fact_type(data_type=data_type)
        body = [{'fact_type_id': fact_type['id']}]
        for input_value, expected_value in values.items():
            body[0]['value'] = input_value
            result = self.fetch(
                f'/projects/{self.project["id"]}/facts',
                method='POST', body=json.dumps(body).encode('utf-8'),
                headers=self.headers)
            self.assertEqual(204, result.code, f'Failure for {input_value!r}')

            result = self.fetch(f'/projects/{self.project["id"]}/facts',
                                headers=self.headers)
            self.assertEqual(200, result.code)
            data = json.loads(result.body)
            self.assertEqual(expected_value, data[0]['value'])

    def test_supported_boolean_formats(self):
        self.verify_expectations('boolean', {
            'y': True,
            'yes': True,
            't': True,
            'TRUE': True,
            'on': True,
            '1': True,

            'n': False,
            'no': False,
            'f': False,
            'FALSE': False,
            'off': False,
            '0': False,
            '': None,
        })

    def test_supported_timestamp_formats(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        truncated = now.replace(microsecond=0)
        self.verify_expectations('timestamp', {
            now.isoformat(): now.isoformat(),
            now.isoformat(sep=' '): now.isoformat(),
            now.strftime('%Y-%m-%dT%H:%M:%SZ'): truncated.isoformat(),
            now.strftime('%Y-%m-%d %H:%M:%S'): truncated.isoformat(),
            now.strftime('%c'): truncated.isoformat(),  # no TZ means UTC!
            now.strftime('%b %d, %Y %I:%M:%S%p %Z'): truncated.isoformat(),
            now.strftime('%m/%d/%Y %H:%M:%S.%f %Z'): now.isoformat(),
            '': None,
        })

    def test_supported_date_formats(self):
        self.verify_expectations('date', {
            '08/15/22': '2022-08-15',
            '08/15/2022': '2022-08-15',
            '20220815': '2022-08-15',
            '2022-08-15': '2022-08-15',
            '08-15-2022': '2022-08-15',
            'aug-15-2022': '2022-08-15',
            '': None,
        })

    def test_integer_representations(self):
        self.verify_expectations('integer', {
            '1': 1,
            10: 10,
            '-5': -5,
            0: 0,
            '': None,
        })

    def test_decimal_representations(self):
        self.verify_expectations('decimal', {
            '1': 1,
            '1.5': 1.5,
            1.5: 1.5,
            -12.34: -12.34,
            '+12.23': 12.23,
            0.0: 0.0,
            '0': 0.0,
            '': None,
        })

    def test_invalid_fact_values(self):
        boolean_fact = self.create_project_fact_type(data_type='boolean')
        date_fact = self.create_project_fact_type(data_type='date')
        decimal_fact = self.create_project_fact_type(data_type='decimal')
        integer_fact = self.create_project_fact_type(data_type='integer')
        timestamp_fact = self.create_project_fact_type(data_type='timestamp')

        invalid_facts = [
            {'fact_type_id': boolean_fact['id'], 'value': -1},
            {'fact_type_id': boolean_fact['id'], 'value': '42'},
            {'fact_type_id': boolean_fact['id'], 'value': 'nope'},
            {'fact_type_id': date_fact['id'], 'value': time.time()},
            {'fact_type_id': timestamp_fact['id'], 'value': '2002-55-66'},
            {'fact_type_id': timestamp_fact['id'],
             'value': '2002-12-31 24:00'},
            {'fact_type_id': integer_fact['id'], 'value': '1.5'},
            {'fact_type_id': integer_fact['id'], 'value': 'inf'},
            {'fact_type_id': integer_fact['id'], 'value': 'not a number'},
            {'fact_type_id': integer_fact['id'], 'value': {}},
            {'fact_type_id': decimal_fact['id'], 'value': 'not a number'},
        ]
        for invalid_fact in invalid_facts:
            result = self.fetch(
                f'/projects/{self.project["id"]}/facts',
                method='POST',
                body=json.dumps([invalid_fact]).encode('utf-8'),
                headers=self.headers)
            self.assertEqual(
                400, result.code,
                f'Unexpected response for {invalid_fact["value"]}')

    def test_unknown_fact_id(self):
        result = self.fetch(f'/projects/{self.project["id"]}/facts',
                            method='POST',
                            body=b'[{"fact_type_id":-1,"value":""}]',
                            headers=self.headers)
        self.assertEqual(400, result.code)
