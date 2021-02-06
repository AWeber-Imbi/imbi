import json

from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = False

    def test_token_lifecycle(self):
        # Create the token
        response = self.fetch(
            '/authentication-tokens', method='POST', headers=self.headers,
            body='{}', allow_nonstandard_methods=True)
        self.assertEqual(response.code, 200)
        result = json.loads(response.body.decode('utf-8'))
        self.assertEqual(result['username'], self.USERNAME[self.ADMIN_ACCESS])
        for field in {'token', 'created_at', 'expires_at'}:
            self.assertIsNotNone(result[field])

        # Get the token list for the current user with new token
        headers = dict(self.headers)
        headers['Private-Token'] = result['token']
        response = self.fetch('/authentication-tokens', headers=headers)
        self.assertEqual(response.code, 200)
        tokens = json.loads(response.body.decode('utf-8'))
        token_count = len(tokens)
        self.assertGreaterEqual(token_count, 2)

        # Delete the token
        response = self.fetch(
            '/authentication-tokens/{}'.format(headers['Private-Token']),
            method='DELETE', headers=headers)
        self.assertEqual(response.code, 204)

        # Get the collection and ensure there's one less token
        response = self.fetch('/authentication-tokens', headers=self.headers)
        self.assertEqual(response.code, 200)
        tokens = json.loads(response.body.decode('utf-8'))
        self.assertEqual(len(tokens), token_count - 1)
