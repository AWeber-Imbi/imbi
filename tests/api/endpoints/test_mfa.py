"""Tests for MFA endpoints."""

import base64
import datetime
import unittest
from unittest import mock

import pyotp
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models, settings
from imbi_api.auth import password, permissions


class MFAEndpointsTestCase(unittest.TestCase):
    """Test MFA endpoint functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.test_app = app.create_app()

        # Create test user
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            mfa_issuer_name='TestApp',
            mfa_totp_period=30,
            mfa_totp_digits=6,
        )

        # Set up auth context
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        # Set up mock graph database
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

        # Mock encryption for MFA tests (plaintext secrets)
        from imbi_common.auth.encryption import TokenEncryption

        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(
            side_effect=lambda x: x,
        )
        mock_encryptor.encrypt = mock.Mock(
            side_effect=lambda x: x,
        )

        self.encryption_patcher = mock.patch.object(
            TokenEncryption,
            'get_instance',
            return_value=mock_encryptor,
        )
        self.encryption_patcher.start()

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.encryption_patcher.stop()

    def test_get_mfa_status_not_setup(self) -> None:
        """Test MFA status when not setup."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get('/mfa/status')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['enabled'], False)
            self.assertEqual(
                data['backup_codes_remaining'],
                0,
            )

    def test_get_mfa_status_enabled(self) -> None:
        """Test MFA status when enabled."""
        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': True,
            'backup_codes': ['abc123', 'def456', 'ghi789'],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get('/mfa/status')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['enabled'], True)
            self.assertEqual(
                data['backup_codes_remaining'],
                3,
            )

    def test_get_mfa_status_not_enabled(self) -> None:
        """Test MFA status when setup but not enabled."""
        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get('/mfa/status')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['enabled'], False)
            self.assertEqual(
                data['backup_codes_remaining'],
                0,
            )

    def test_setup_mfa_success(self) -> None:
        """Test successful MFA setup."""
        # First call: check existing TOTP (not found)
        # Second call: merge TOTP secret (no return needed)
        self.mock_db.execute.return_value = []
        self.mock_db.merge.return_value = None

        # Mock QR code generation
        mock_qr = mock.Mock()
        mock_img = mock.Mock()
        mock_qr.make_image.return_value = mock_img

        def mock_save(buffer, format):
            buffer.write(b'fake-qr-code-png-data')

        mock_img.save = mock_save

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'qrcode.QRCode',
                return_value=mock_qr,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post('/mfa/setup')

            self.assertEqual(response.status_code, 200)
            data = response.json()

            # Verify response structure
            self.assertIn('secret', data)
            self.assertIn('provisioning_uri', data)
            self.assertIn('backup_codes', data)
            self.assertIn('qr_code', data)

            # Verify secret format (base32)
            self.assertTrue(data['secret'].isalnum())
            self.assertTrue(data['secret'].isupper())

            # Verify provisioning URI format
            self.assertTrue(
                data['provisioning_uri'].startswith('otpauth://totp/')
            )
            self.assertIn(
                'TestApp',
                data['provisioning_uri'],
            )

            # Verify backup codes (10 codes, 8-char hex)
            self.assertEqual(len(data['backup_codes']), 10)
            for code in data['backup_codes']:
                self.assertEqual(len(code), 8)
                self.assertTrue(all(c in '0123456789abcdef' for c in code))

            # Verify QR code (base64-encoded PNG)
            try:
                base64.b64decode(data['qr_code'])
            except (
                ValueError,
                TypeError,
                base64.binascii.Error,
            ) as err:
                self.fail(f'QR code is not valid base64: {err}')

    def test_verify_mfa_valid_code(self) -> None:
        """Test MFA verification with valid code."""
        secret = 'JBSWY3DPEHPK3PXP'
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        totp_data = {
            'secret': secret,
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                json={'code': valid_code},
            )

            self.assertEqual(response.status_code, 204)

    def test_verify_mfa_invalid_code(self) -> None:
        """Test MFA verification with invalid code."""
        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                json={'code': '000000'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'Invalid MFA code',
            )

    def test_verify_mfa_not_setup(self) -> None:
        """Test MFA verification when not setup."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                json={'code': '123456'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.json()['detail'],
                'MFA not setup for this user',
            )

    def test_disable_mfa_success(self) -> None:
        """Test MFA disable with valid password."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'current_password': 'testpassword123'},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_invalid_password(self) -> None:
        """Test MFA disable with invalid password."""
        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'current_password': 'wrongpassword'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'Invalid password',
            )

    def test_disable_mfa_no_password_hash(self) -> None:
        """Test MFA disable when user has no password."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=oauth_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'current_password': 'anything'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'MFA code required to disable MFA (OAuth-only account)',
            )

    def test_verify_mfa_decryption_failure(self) -> None:
        """Test MFA verification when decryption fails."""
        totp_data = {
            'secret': 'encrypted-secret-here',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        # Mock encryptor that fails to decrypt
        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(
            side_effect=ValueError('Decryption failed'),
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_common.auth.encryption.TokenEncryption.get_instance',
                return_value=mock_encryptor,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                json={'code': '123456'},
            )

            self.assertEqual(response.status_code, 500)
            self.assertIn(
                'Failed to decrypt MFA secret',
                response.json()['detail'],
            )

    def test_verify_mfa_decryption_returns_none(self) -> None:
        """Test MFA verification when decryption returns None."""
        totp_data = {
            'secret': 'encrypted-secret-here',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        # Mock encryptor that returns None
        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(return_value=None)

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_common.auth.encryption.TokenEncryption.get_instance',
                return_value=mock_encryptor,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                json={'code': '123456'},
            )

            self.assertEqual(response.status_code, 500)
            self.assertIn(
                'Failed to decrypt MFA secret',
                response.json()['detail'],
            )

    def test_verify_mfa_with_backup_code(self) -> None:
        """Test MFA verification with backup code."""
        secret = 'JBSWY3DPEHPK3PXP'
        backup_code_plain = 'backup12'
        backup_code_hash = password.hash_password(
            backup_code_plain,
        )

        totp_data = {
            'secret': secret,
            'enabled': False,
            'backup_codes': [backup_code_hash, 'other_hash'],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                json={'code': backup_code_plain},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_password_required(self) -> None:
        """Test MFA disable requires password."""
        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            # No password provided
            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'Password required to disable MFA',
            )

    def test_disable_mfa_oauth_user_with_valid_mfa_code(
        self,
    ) -> None:
        """Test OAuth user can disable MFA with valid code."""
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=oauth_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        secret = 'JBSWY3DPEHPK3PXP'
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'mfa_code': valid_code},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_oauth_user_with_backup_code(
        self,
    ) -> None:
        """Test OAuth user can disable MFA with backup code."""
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=oauth_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        secret = 'JBSWY3DPEHPK3PXP'
        backup_code_plain = 'backup99'
        backup_code_hash = password.hash_password(
            backup_code_plain,
        )

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [backup_code_hash],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'mfa_code': backup_code_plain},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_oauth_user_with_invalid_mfa_code(
        self,
    ) -> None:
        """Test OAuth user cannot disable MFA with bad code."""
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=oauth_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        secret = 'JBSWY3DPEHPK3PXP'

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'mfa_code': '000000'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'Invalid MFA code',
            )

    def test_disable_mfa_oauth_user_mfa_not_enabled(
        self,
    ) -> None:
        """Test OAuth user cannot disable MFA when off."""
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=oauth_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'mfa_code': '123456'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.json()['detail'],
                'MFA not enabled',
            )

    def test_disable_mfa_oauth_user_decryption_failure(
        self,
    ) -> None:
        """Test OAuth user MFA disable when decrypt fails."""
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=oauth_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        totp_data = {
            'secret': 'encrypted-secret',
            'enabled': True,
            'backup_codes': [],
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ),
        }

        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        # Mock encryptor that fails to decrypt
        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(
            side_effect=TypeError('Decryption type error'),
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_common.auth.encryption.TokenEncryption.get_instance',
                return_value=mock_encryptor,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                json={'mfa_code': '123456'},
            )

            self.assertEqual(response.status_code, 500)
            self.assertIn(
                'Failed to decrypt MFA secret',
                response.json()['detail'],
            )
