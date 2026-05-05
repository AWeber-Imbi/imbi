"""Tests for identity-flow state JWT helpers."""

import time
import unittest
from unittest import mock

import jwt

from imbi_api import settings
from imbi_api.identity import state


class EncodeIdentityStateTestCase(unittest.TestCase):
    """Verify identity state JWTs round-trip cleanly."""

    def setUp(self) -> None:
        self.auth = settings.Auth(jwt_secret='identity-state-test-secret')

    def test_round_trip_minimal(self) -> None:
        token = state.encode_identity_state(
            plugin_id='p-1',
            plugin_slug='oidc',
            redirect_uri='https://imbi.test/callback',
            auth_settings=self.auth,
        )
        decoded = state.decode_identity_state(token, auth_settings=self.auth)
        self.assertEqual(decoded.plugin_id, 'p-1')
        self.assertEqual(decoded.provider, 'oidc')
        self.assertEqual(decoded.redirect_uri, 'https://imbi.test/callback')
        self.assertEqual(decoded.intent, 'identity')

    def test_round_trip_full_payload(self) -> None:
        token = state.encode_identity_state(
            plugin_id='p-2',
            plugin_slug='aws-sso',
            redirect_uri='https://imbi.test/cb',
            return_to='/projects/x',
            code_verifier='verifier-abc',
            actor_user_id='user-7',
            auth_settings=self.auth,
        )
        decoded = state.decode_identity_state(token, auth_settings=self.auth)
        self.assertEqual(decoded.plugin_id, 'p-2')
        self.assertEqual(decoded.return_to, '/projects/x')
        self.assertEqual(decoded.code_verifier, 'verifier-abc')
        self.assertEqual(decoded.actor_user_id, 'user-7')


class DecodeIdentityStateTestCase(unittest.TestCase):
    """Verify decode rejects tampered, expired, and wrong-intent tokens."""

    def setUp(self) -> None:
        self.auth = settings.Auth(jwt_secret='identity-state-test-secret')

    def test_invalid_signature_raises_value_error(self) -> None:
        token = state.encode_identity_state(
            plugin_id='p-1',
            plugin_slug='oidc',
            redirect_uri='https://imbi.test/cb',
            auth_settings=self.auth,
        )
        wrong = settings.Auth(jwt_secret='different-secret')
        with self.assertRaises(ValueError):
            state.decode_identity_state(token, auth_settings=wrong)

    def test_expired_token_raises_value_error(self) -> None:
        with mock.patch.object(state.time, 'time', return_value=1000):
            token = state.encode_identity_state(
                plugin_id='p-1',
                plugin_slug='oidc',
                redirect_uri='https://imbi.test/cb',
                auth_settings=self.auth,
            )
        # 30 minutes later — well beyond default 600s window.
        with mock.patch.object(state.time, 'time', return_value=1000 + 1800):
            with self.assertRaises(ValueError) as ctx:
                state.decode_identity_state(token, auth_settings=self.auth)
        self.assertIn('expired', str(ctx.exception))

    def test_wrong_intent_raises_value_error(self) -> None:
        # Hand-craft a 'login' intent token to confirm decode rejects it.
        payload = {
            'provider': 'oidc',
            'nonce': 'n',
            'redirect_uri': 'https://imbi.test/cb',
            'timestamp': int(time.time()),
            'intent': 'login',
            'plugin_id': 'p-1',
        }
        token = jwt.encode(
            payload,
            self.auth.jwt_secret,
            algorithm=self.auth.jwt_algorithm,
        )
        with self.assertRaises(ValueError):
            state.decode_identity_state(token, auth_settings=self.auth)

    def test_missing_plugin_id_raises_value_error(self) -> None:
        payload = {
            'provider': 'oidc',
            'nonce': 'n',
            'redirect_uri': 'https://imbi.test/cb',
            'timestamp': int(time.time()),
            'intent': 'identity',
            'plugin_id': None,
        }
        token = jwt.encode(
            payload,
            self.auth.jwt_secret,
            algorithm=self.auth.jwt_algorithm,
        )
        with self.assertRaises(ValueError):
            state.decode_identity_state(token, auth_settings=self.auth)
