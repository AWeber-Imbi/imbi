import json

from tests import common


class AsyncHTTPTestCase(common.AsyncHTTPTestCase):

    ADMIN = True

    def test_permission_values(self):
        result = self.fetch('/settings/permissions', headers=self.headers)
        self.assertEqual(result.code, 200)
        values = json.loads(result.body.decode('utf-8'))
        self.assertListEqual(values, list(self._app.settings['permissions']))


class AsyncHTTPUnauthorizedTestCase(common.AsyncHTTPTestCase):

    ADMIN = False

    def test_permission_values(self):
        # Validate response
        result = self.fetch('/settings/permissions', headers=self.headers)
        self.assertEqual(result.code, 403)
