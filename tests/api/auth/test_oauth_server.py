"""Tests for the OAuth2 Authorization Server endpoints.

Covers AS metadata, dynamic client registration, the authorization
endpoint (PKCE + cookie-based user identity), and the
authorization_code token grant.
"""

import base64
import hashlib
import json
from unittest import mock

from fastapi import testclient
from imbi_common import graph
from imbi_common.auth import core

from imbi_api import models, scoring, settings
from imbi_api.auth import authorization_codes
from tests import support

_VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


class OAuthServerTestCase(support.SharedAppTestCase):
    """Authorization Server endpoint behavior."""

    def setUp(self) -> None:
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long-xxxx',
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.mock_valkey = mock.AsyncMock()
        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: self.mock_valkey
        )
        self.client = testclient.TestClient(self.test_app)

        self._settings_patch = mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=self.auth_settings,
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

    def _client_node(self) -> models.OAuthClient:
        return models.OAuthClient(
            client_id='mcp_test',
            redirect_uris=['https://app.example/cb'],
        )

    # -- metadata ---------------------------------------------------------

    def test_metadata(self) -> None:
        resp = self.client.get('/.well-known/oauth-authorization-server')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('issuer', body)
        self.assertTrue(
            body['authorization_endpoint'].endswith('/auth/authorize')
        )
        self.assertTrue(body['token_endpoint'].endswith('/auth/token'))
        self.assertTrue(
            body['registration_endpoint'].endswith('/auth/register')
        )
        self.assertEqual(body['code_challenge_methods_supported'], ['S256'])
        self.assertIn('authorization_code', body['grant_types_supported'])

    # -- registration (DCR) ----------------------------------------------

    def test_register_success(self) -> None:
        self.mock_db.create.return_value = None
        resp = self.client.post(
            '/auth/register',
            json={
                'redirect_uris': ['https://app.example/cb'],
                'client_name': 'Test Client',
            },
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body['client_id'].startswith('mcp_'))
        self.assertEqual(body['token_endpoint_auth_method'], 'none')
        self.mock_db.create.assert_awaited_once()

    def test_register_rejects_non_loopback_http(self) -> None:
        resp = self.client.post(
            '/auth/register',
            json={'redirect_uris': ['http://evil.example/cb']},
        )
        self.assertEqual(resp.status_code, 400)
        self.mock_db.create.assert_not_called()

    def test_register_allows_loopback(self) -> None:
        self.mock_db.create.return_value = None
        resp = self.client.post(
            '/auth/register',
            json={'redirect_uris': ['http://127.0.0.1:8765/callback']},
        )
        self.assertEqual(resp.status_code, 201)

    def test_register_disabled(self) -> None:
        self.auth_settings.dcr_enabled = False
        resp = self.client.post(
            '/auth/register',
            json={'redirect_uris': ['https://app.example/cb']},
        )
        self.assertEqual(resp.status_code, 403)

    def test_register_rejects_fragment_redirect(self) -> None:
        resp = self.client.post(
            '/auth/register',
            json={'redirect_uris': ['https://app.example/cb#frag']},
        )
        self.assertEqual(resp.status_code, 400)
        self.mock_db.create.assert_not_called()

    def test_register_rejects_unsupported_grant_types(self) -> None:
        resp = self.client.post(
            '/auth/register',
            json={
                'redirect_uris': ['https://app.example/cb'],
                'grant_types': ['client_credentials'],
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.mock_db.create.assert_not_called()

    def test_register_rejects_unsupported_response_types(self) -> None:
        resp = self.client.post(
            '/auth/register',
            json={
                'redirect_uris': ['https://app.example/cb'],
                'response_types': ['token'],
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.mock_db.create.assert_not_called()

    # -- authorize --------------------------------------------------------

    def _authorize(self, **overrides: str) -> object:
        params = {
            'response_type': 'code',
            'client_id': 'mcp_test',
            'redirect_uri': 'https://app.example/cb',
            'code_challenge': _challenge(_VERIFIER),
            'code_challenge_method': 'S256',
            'state': 'xyz',
        }
        params.update(overrides)
        return self.client.get(
            '/auth/authorize', params=params, follow_redirects=False
        )

    def test_authorize_unknown_client(self) -> None:
        self.mock_db.match.return_value = []
        resp = self._authorize()
        self.assertEqual(resp.status_code, 400)

    def test_authorize_unregistered_redirect(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        resp = self._authorize(redirect_uri='https://attacker.example/cb')
        self.assertEqual(resp.status_code, 400)

    def test_authorize_anonymous_redirects_to_login(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        resp = self._authorize()
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login?return_to=', resp.headers['location'])

    def test_authorize_issues_code_when_authenticated(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        self.mock_valkey.set.return_value = True
        token = core.create_access_token(
            'user@example.com', auth_settings=self.auth_settings
        )
        self.client.cookies.set('imbi_access_token', token)
        resp = self._authorize()
        self.assertEqual(resp.status_code, 302)
        location = resp.headers['location']
        self.assertTrue(location.startswith('https://app.example/cb?'))
        self.assertIn('code=', location)
        self.assertIn('state=xyz', location)
        self.mock_valkey.set.assert_awaited_once()

    def test_authorize_rejects_plain_pkce(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        resp = self._authorize(code_challenge_method='plain')
        # redirect_uri is valid, so the protocol error redirects to it
        self.assertEqual(resp.status_code, 302)
        self.assertIn('error=invalid_request', resp.headers['location'])

    # -- token (authorization_code grant) --------------------------------

    def _payload(self) -> str:
        return json.dumps(
            {
                'client_id': 'mcp_test',
                'redirect_uri': 'https://app.example/cb',
                'code_challenge': _challenge(_VERIFIER),
                'principal_id': 'user@example.com',
                'scope': None,
            }
        )

    def test_token_code_success(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        self.mock_valkey.getdel.return_value = self._payload()
        with mock.patch(
            'imbi_api.auth.tokens.issue_token_pair',
            new=mock.AsyncMock(return_value=('access-tok', 'refresh-tok', {})),
        ):
            resp = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'authorization_code',
                    'code': 'thecode',
                    'redirect_uri': 'https://app.example/cb',
                    'client_id': 'mcp_test',
                    'code_verifier': _VERIFIER,
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['access_token'], 'access-tok')
        self.assertEqual(body['refresh_token'], 'refresh-tok')

    def test_token_code_pkce_mismatch(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        self.mock_valkey.getdel.return_value = self._payload()
        resp = self.client.post(
            '/auth/token',
            data={
                'grant_type': 'authorization_code',
                'code': 'thecode',
                'redirect_uri': 'https://app.example/cb',
                'client_id': 'mcp_test',
                'code_verifier': 'wrong-verifier',
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_token_code_already_used(self) -> None:
        self.mock_db.match.return_value = [self._client_node()]
        self.mock_valkey.getdel.return_value = None  # consumed
        resp = self.client.post(
            '/auth/token',
            data={
                'grant_type': 'authorization_code',
                'code': 'thecode',
                'redirect_uri': 'https://app.example/cb',
                'client_id': 'mcp_test',
                'code_verifier': _VERIFIER,
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_token_unsupported_grant(self) -> None:
        resp = self.client.post('/auth/token', data={'grant_type': 'password'})
        self.assertEqual(resp.status_code, 400)

    def test_verify_pkce_non_ascii_verifier(self) -> None:
        """A non-ASCII verifier is a mismatch, not a 500."""
        self.assertFalse(
            authorization_codes.verify_pkce('verifiér', _challenge(_VERIFIER))
        )
