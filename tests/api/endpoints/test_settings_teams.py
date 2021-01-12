import json
import uuid

from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True

    def test_teams(self):
        # Setup test values
        records = sorted([
            {
                'name': str(uuid.uuid4()),
                'slug': str(uuid.uuid4().hex),
                'icon_class': 'fas fa-blind',
                'group': 'imbi'
            },
            {
                'name': str(uuid.uuid4()),
                'slug': str(uuid.uuid4().hex),
                'icon_class': 'fas fa-blind',
                'group': None
            }
        ], key=lambda x: x['name'])

        # Insert new records
        for record in records:
            result = self.fetch(
                '/admin/team', method='POST',
                body=json.dumps(record).encode('utf-8'),
                headers=self.headers)
            self.assertEqual(result.code, 200)
            new_value = json.loads(result.body.decode('utf-8'))
            self.assertDictEqual(new_value, record)

        # Validate response
        result = self.fetch('/settings/teams', headers=self.headers)
        self.assertEqual(result.code, 200)
        values = json.loads(result.body.decode('utf-8'))
        for offset, record in enumerate(values):
            for key in {'created_at', 'modified_at'}:
                del record[key]
            self.assertDictEqual(record, records[offset])
