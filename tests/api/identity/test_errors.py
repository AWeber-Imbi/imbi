"""Tests for identity-flow error types."""

import unittest

from imbi.api.identity import errors


class IdentityRequiredErrorTestCase(unittest.TestCase):
    """Verify IdentityRequiredError preserves integration_id + start_url."""

    def test_carries_integration_id_and_start_url(self) -> None:
        exc = errors.IdentityRequiredError(
            integration_id='abc',
            start_url='/me/identities/abc/start',
        )
        self.assertEqual(exc.integration_id, 'abc')
        self.assertEqual(exc.start_url, '/me/identities/abc/start')
        self.assertIn('abc', str(exc))


class IdentityRefreshFailedTestCase(unittest.TestCase):
    """Marker exception for terminal refresh-grant failures."""

    def test_carries_message(self) -> None:
        exc = errors.IdentityRefreshFailed('expired')
        self.assertEqual(str(exc), 'expired')


class IdentityRevokedErrorTestCase(unittest.TestCase):
    """Marker exception for revoked connections."""

    def test_can_be_raised(self) -> None:
        with self.assertRaises(errors.IdentityRevokedError):
            raise errors.IdentityRevokedError('token revoked')
