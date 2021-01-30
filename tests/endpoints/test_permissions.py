import json

from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True

    def test_permission_values(self):
        result = self.fetch('/permissions', headers=self.headers)
        self.assertEqual(result.code, 200)
        values = json.loads(result.body.decode('utf-8'))
        self.assertListEqual(values, list(self._app.settings['permissions']))


class AsyncHTTPUnauthorizedTestCase(base.TestCaseWithReset):

    def test_permission_values(self):
        result = self.fetch('/permissions', headers=self.headers)
        self.assertEqual(result.code, 403)
