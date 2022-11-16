from tests import base


class AsyncHTTPTestCase(base.TestCase):

    def test_status_ok(self):
        response = self.fetch('/metrics')
        self.assertEqual(response.code, 200)
        self.assertIn(
            '# TYPE postgres_pool_free gauge', response.body.decode('utf-8'))
        self.assertIn(
            'postgres_pool_size{host=', response.body.decode('utf-8'))
