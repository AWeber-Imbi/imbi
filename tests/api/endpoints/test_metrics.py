from tests import base


class AsyncHTTPTestCase(base.TestCase):

    def test_status_ok(self):
        response = self.fetch('/metrics', headers=self.headers)
        self.assertEqual(response.code, 200)
        self.validate_response(response)
