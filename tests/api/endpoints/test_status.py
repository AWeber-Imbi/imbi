from tests import base


class AsyncHTTPTestCase(base.TestCase):

    def test_status_ok(self):
        response = self.fetch('/status', headers=self.headers)
        self.assertEqual(response.code, 200)
        self.validate_response(response)

    def test_status_error(self):
        self._app._ready_to_serve = False
        response = self.fetch('/status', headers=self.headers)
        self.assertEqual(response.code, 503)
        self.validate_response(response)
