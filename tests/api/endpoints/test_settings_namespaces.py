import json
import uuid

from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = ['v1.namespaces']

    def test_namespaces(self):
        # Setup test values
        records = sorted([
            {
                'name': str(uuid.uuid4()),
                'slug': str(uuid.uuid4().hex),
                'icon_class': 'fas fa-blind',
                'maintained_by': []
            },
            {
                'name': str(uuid.uuid4()),
                'slug': str(uuid.uuid4().hex),
                'icon_class': 'fas fa-blind',
                'maintained_by': []
            }
        ], key=lambda x: x['name'])

        # Insert new records
        for record in records:
            result = self.fetch(
                '/admin/namespace', method='POST',
                body=json.dumps(record).encode('utf-8'),
                headers=self.headers)
            self.assertEqual(result.code, 200)
            new_value = json.loads(result.body.decode('utf-8'))
            for key in ['created_by', 'last_modified_by']:
                del new_value[key]
            self.assertDictEqual(new_value, record)

        # Validate response
        result = self.fetch('/settings/namespaces', headers=self.headers)
        self.assertEqual(result.code, 200)
        values = json.loads(result.body.decode('utf-8'))
        for offset, record in enumerate(values):
            self.assertDictEqual(record, records[offset])
