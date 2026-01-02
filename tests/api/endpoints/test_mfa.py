"""Tests for MFA endpoints."""

import base64
import datetime
import unittest
from unittest import mock

import pyotp
from fastapi import testclient

from imbi import app, models, settings
from imbi.auth import core


class MFAEndpointsTestCase(unittest.TestCase):
    """Test MFA endpoint functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.app = app.create_app()
        self.client = testclient.TestClient(self.app)

        # Create test user
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            mfa_issuer_name='TestApp',
            mfa_totp_period=30,
            mfa_totp_digits=6,
        )

        # Mock encryption for MFA tests (plaintext secrets in tests)
        from imbi.auth.encryption import TokenEncryption

        mock_encryptor = mock.Mock()
        # decrypt() returns the input as-is (plaintext)
        mock_encryptor.decrypt = mock.Mock(side_effect=lambda x: x)
        # encrypt() returns the input as-is (plaintext)
        mock_encryptor.encrypt = mock.Mock(side_effect=lambda x: x)

        self.encryption_patcher = mock.patch.object(
            TokenEncryption, 'get_instance', return_value=mock_encryptor
        )
        self.encryption_patcher.start()

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.encryption_patcher.stop()

    def _create_mock_run(
        self, totp_data: dict | None = None, include_consume: bool = False
    ):
        """Create mock_run_side_effect with consistent auth handling.

        Args:
            totp_data: TOTP secret data to return (None means not found)
            include_consume: Whether to add consume mock
        """

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            if include_consume:
                mock_result.consume = mock.AsyncMock()

            # Check TOTPSecret queries first (most specific)
            if 'TOTPSecret' in query:
                if totp_data:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'t': totp_data}]
                    )
                else:
                    mock_result.data = mock.AsyncMock(return_value=[])
            # Auth queries
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        return mock_run_side_effect

    def test_get_mfa_status_not_setup(self) -> None:
        """Test MFA status when not setup."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/mfa/status',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['enabled'], False)
            self.assertEqual(data['backup_codes_remaining'], 0)

    def test_get_mfa_status_enabled(self) -> None:
        """Test MFA status when enabled."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': True,
            'backup_codes': ['abc123', 'def456', 'ghi789'],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(totp_data),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/mfa/status',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['enabled'], True)
            self.assertEqual(data['backup_codes_remaining'], 3)

    def test_get_mfa_status_not_enabled(self) -> None:
        """Test MFA status when setup but not enabled."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(totp_data),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/mfa/status',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['enabled'], False)
            self.assertEqual(data['backup_codes_remaining'], 0)

    def test_setup_mfa_success(self) -> None:
        """Test successful MFA setup."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        # Mock QR code generation
        mock_qr = mock.Mock()
        mock_img = mock.Mock()
        mock_qr.make_image.return_value = mock_img

        # Mock save to write fake PNG data
        def mock_save(buffer, format):
            buffer.write(b'fake-qr-code-png-data')

        mock_img.save = mock_save

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(None, include_consume=True),
            ),
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('qrcode.QRCode', return_value=mock_qr),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/setup',
                headers={'Authorization': f'Bearer {access_token}'},
            )

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
            self.assertIn('TestApp', data['provisioning_uri'])

            # Verify backup codes (10 codes, 8-character hex)
            self.assertEqual(len(data['backup_codes']), 10)
            for code in data['backup_codes']:
                self.assertEqual(len(code), 8)
                self.assertTrue(all(c in '0123456789abcdef' for c in code))

            # Verify QR code (base64-encoded PNG)
            try:
                base64.b64decode(data['qr_code'])
            except (ValueError, TypeError, base64.binascii.Error) as err:
                self.fail(f'QR code is not valid base64: {err}')

    def test_verify_mfa_valid_code(self) -> None:
        """Test MFA verification with valid code."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        # Generate valid TOTP code
        secret = 'JBSWY3DPEHPK3PXP'
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        totp_data = {
            'secret': secret,
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(
                    totp_data, include_consume=True
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'code': valid_code},
            )

            self.assertEqual(response.status_code, 204)

    def test_verify_mfa_invalid_code(self) -> None:
        """Test MFA verification with invalid code."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(totp_data),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'code': '000000'},  # Invalid code
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['detail'], 'Invalid MFA code')

    def test_verify_mfa_not_setup(self) -> None:
        """Test MFA verification when not setup."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'code': '123456'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.json()['detail'], 'MFA not setup for this user'
            )

    def test_disable_mfa_success(self) -> None:
        """Test MFA disable with valid password."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(None, include_consume=True),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'current_password': 'testpassword123'},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_invalid_password(self) -> None:
        """Test MFA disable with invalid password."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'current_password': 'wrongpassword'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['detail'], 'Invalid password')

    def test_disable_mfa_no_password_hash(self) -> None:
        """Test MFA disable when user has no password."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token, _ = core.create_access_token(
            oauth_user.email, self.auth_settings
        )

        def mock_run_oauth(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = oauth_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_oauth),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'current_password': 'anything'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'MFA code required to disable MFA (OAuth-only account)',
            )

    def test_verify_mfa_decryption_failure(self) -> None:
        """Test MFA verification when decryption fails."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        totp_data = {
            'secret': 'encrypted-secret-here',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        # Mock encryptor that fails to decrypt
        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(
            side_effect=ValueError('Decryption failed')
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(totp_data)
            ),
            mock.patch(
                'imbi.auth.encryption.TokenEncryption.get_instance',
                return_value=mock_encryptor,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'code': '123456'},
            )

            self.assertEqual(response.status_code, 500)
            self.assertIn(
                'Failed to decrypt MFA secret', response.json()['detail']
            )

    def test_verify_mfa_decryption_returns_none(self) -> None:
        """Test MFA verification when decryption returns None."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        totp_data = {
            'secret': 'encrypted-secret-here',
            'enabled': False,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        # Mock encryptor that returns None
        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(return_value=None)

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(totp_data)
            ),
            mock.patch(
                'imbi.auth.encryption.TokenEncryption.get_instance',
                return_value=mock_encryptor,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'code': '123456'},
            )

            self.assertEqual(response.status_code, 500)
            self.assertIn(
                'Failed to decrypt MFA secret', response.json()['detail']
            )

    def test_verify_mfa_with_backup_code(self) -> None:
        """Test MFA verification with backup code."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        secret = 'JBSWY3DPEHPK3PXP'
        backup_code_plain = 'backup12'
        backup_code_hash = core.hash_password(backup_code_plain)

        totp_data = {
            'secret': secret,
            'enabled': False,
            'backup_codes': [backup_code_hash, 'other_hash'],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(
                    totp_data, include_consume=True
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/mfa/verify',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'code': backup_code_plain},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_password_required(self) -> None:
        """Test MFA disable requires password for password-based users."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            # No password provided
            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'], 'Password required to disable MFA'
            )

    def test_disable_mfa_oauth_user_with_valid_mfa_code(self) -> None:
        """Test OAuth-only user can disable MFA with valid MFA code."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token, _ = core.create_access_token(
            oauth_user.email, self.auth_settings
        )

        # Generate valid TOTP code
        secret = 'JBSWY3DPEHPK3PXP'
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        def mock_run_oauth_with_mfa(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            if 'TOTPSecret' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = oauth_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_oauth_with_mfa),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'mfa_code': valid_code},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_oauth_user_with_backup_code(self) -> None:
        """Test OAuth-only user can disable MFA with backup code."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token, _ = core.create_access_token(
            oauth_user.email, self.auth_settings
        )

        secret = 'JBSWY3DPEHPK3PXP'
        backup_code_plain = 'backup99'
        backup_code_hash = core.hash_password(backup_code_plain)

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [backup_code_hash],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        def mock_run_oauth_with_mfa(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            if 'TOTPSecret' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = oauth_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_oauth_with_mfa),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'mfa_code': backup_code_plain},
            )

            self.assertEqual(response.status_code, 204)

    def test_disable_mfa_oauth_user_with_invalid_mfa_code(self) -> None:
        """Test OAuth-only user cannot disable MFA with invalid code."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token, _ = core.create_access_token(
            oauth_user.email, self.auth_settings
        )

        secret = 'JBSWY3DPEHPK3PXP'

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        def mock_run_oauth_with_mfa(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'TOTPSecret' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = oauth_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_oauth_with_mfa),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'mfa_code': '000000'},  # Invalid code
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['detail'], 'Invalid MFA code')

    def test_disable_mfa_oauth_user_mfa_not_enabled(self) -> None:
        """Test OAuth-only user cannot disable MFA when not enabled."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token, _ = core.create_access_token(
            oauth_user.email, self.auth_settings
        )

        def mock_run_oauth_no_mfa(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'TOTPSecret' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = oauth_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_oauth_no_mfa),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'mfa_code': '123456'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()['detail'], 'MFA not enabled')

    def test_disable_mfa_oauth_user_decryption_failure(self) -> None:
        """Test OAuth-only user MFA disable when decryption fails."""
        # User without password (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token, _ = core.create_access_token(
            oauth_user.email, self.auth_settings
        )

        totp_data = {
            'secret': 'encrypted-secret',
            'enabled': True,
            'backup_codes': [],
            'created_at': datetime.datetime.now(datetime.UTC),
        }

        # Mock encryptor that fails to decrypt
        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(
            side_effect=TypeError('Decryption type error')
        )

        def mock_run_oauth_with_mfa(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'TOTPSecret' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'username' in query:
                user_dict = oauth_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_oauth_with_mfa),
            mock.patch(
                'imbi.auth.encryption.TokenEncryption.get_instance',
                return_value=mock_encryptor,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.request(
                'DELETE',
                '/mfa/disable',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'mfa_code': '123456'},
            )

            self.assertEqual(response.status_code, 500)
            self.assertIn(
                'Failed to decrypt MFA secret', response.json()['detail']
            )
