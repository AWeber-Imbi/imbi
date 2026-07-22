"""Tests for clickhouse.privacy module."""

import json
import unittest

from imbi_common.clickhouse import privacy


class HashIPAddressTestCase(unittest.TestCase):
    """Test cases for hash_ip_address function."""

    def test_hash_ipv4_address(self) -> None:
        """Test hashing IPv4 address."""
        result = privacy.hash_ip_address('192.168.1.1')
        # SHA256 produces 64 character hex string
        self.assertEqual(len(result), 64)
        # Verify deterministic hashing
        self.assertEqual(
            result,
            'c5eb5a4cc76a5cdb16e79864b9ccd26c3553f0c396d0a21bafb7be71c1efcd8c',
        )

    def test_hash_ipv6_address(self) -> None:
        """Test hashing IPv6 address."""
        result = privacy.hash_ip_address('2001:0db8:85a3::8a2e:0370:7334')
        self.assertEqual(len(result), 64)
        # Verify deterministic hashing
        self.assertEqual(
            result,
            privacy.hash_ip_address('2001:0db8:85a3::8a2e:0370:7334'),
        )

    def test_hash_localhost(self) -> None:
        """Test hashing localhost addresses."""
        ipv4_localhost = privacy.hash_ip_address('127.0.0.1')
        ipv6_localhost = privacy.hash_ip_address('::1')

        self.assertEqual(len(ipv4_localhost), 64)
        self.assertEqual(len(ipv6_localhost), 64)
        self.assertNotEqual(ipv4_localhost, ipv6_localhost)

    def test_hash_same_ip_produces_same_hash(self) -> None:
        """Test that hashing same IP produces same hash."""
        ip = '10.0.0.1'
        hash1 = privacy.hash_ip_address(ip)
        hash2 = privacy.hash_ip_address(ip)
        self.assertEqual(hash1, hash2)

    def test_hash_different_ips_produce_different_hashes(self) -> None:
        """Test that different IPs produce different hashes."""
        hash1 = privacy.hash_ip_address('192.168.1.1')
        hash2 = privacy.hash_ip_address('192.168.1.2')
        self.assertNotEqual(hash1, hash2)


class TruncateIPToSubnetTestCase(unittest.TestCase):
    """Test cases for truncate_ip_to_subnet function."""

    def test_truncate_ipv4_to_24_subnet(self) -> None:
        """Test IPv4 truncation to /24 subnet."""
        # Last octet should be zeroed
        self.assertEqual(
            privacy.truncate_ip_to_subnet('192.168.1.100'), '192.168.1.0'
        )
        self.assertEqual(
            privacy.truncate_ip_to_subnet('10.20.30.255'), '10.20.30.0'
        )
        self.assertEqual(
            privacy.truncate_ip_to_subnet('172.16.0.1'), '172.16.0.0'
        )

    def test_truncate_ipv4_already_network_address(self) -> None:
        """Test IPv4 that's already a network address."""
        self.assertEqual(
            privacy.truncate_ip_to_subnet('192.168.1.0'), '192.168.1.0'
        )

    def test_truncate_ipv6_to_48_subnet(self) -> None:
        """Test IPv6 truncation to /48 subnet."""
        # Should truncate to /48
        self.assertEqual(
            privacy.truncate_ip_to_subnet(
                '2001:0db8:85a3:0000:0000:8a2e:0370:7334'
            ),
            '2001:db8:85a3::',
        )
        self.assertEqual(
            privacy.truncate_ip_to_subnet(
                '2001:db8:1234:5678:9abc:def0:1234:5678'
            ),
            '2001:db8:1234::',
        )

    def test_truncate_ipv6_compressed_notation(self) -> None:
        """Test IPv6 with compressed notation."""
        self.assertEqual(
            privacy.truncate_ip_to_subnet('2001:db8::1'), '2001:db8::'
        )
        self.assertEqual(privacy.truncate_ip_to_subnet('::1'), '::')

    def test_truncate_ipv6_already_network_address(self) -> None:
        """Test IPv6 that's already a network address."""
        self.assertEqual(
            privacy.truncate_ip_to_subnet('2001:db8::'), '2001:db8::'
        )

    def test_truncate_localhost_addresses(self) -> None:
        """Test truncation of localhost addresses."""
        self.assertEqual(
            privacy.truncate_ip_to_subnet('127.0.0.1'), '127.0.0.0'
        )
        self.assertEqual(privacy.truncate_ip_to_subnet('::1'), '::')

    def test_truncate_invalid_ip_raises_value_error(self) -> None:
        """Test that invalid IP raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            privacy.truncate_ip_to_subnet('not-an-ip')
        self.assertIn('Invalid IP address', str(cm.exception))

    def test_truncate_empty_string_raises_value_error(self) -> None:
        """Test that empty string raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            privacy.truncate_ip_to_subnet('')
        self.assertIn('Invalid IP address', str(cm.exception))

    def test_truncate_private_network_addresses(self) -> None:
        """Test truncation of various private network addresses."""
        # RFC 1918 private addresses
        self.assertEqual(privacy.truncate_ip_to_subnet('10.0.0.1'), '10.0.0.0')
        self.assertEqual(
            privacy.truncate_ip_to_subnet('172.16.0.1'), '172.16.0.0'
        )
        self.assertEqual(
            privacy.truncate_ip_to_subnet('192.168.0.1'), '192.168.0.0'
        )


class ParseUserAgentTestCase(unittest.TestCase):
    """Test cases for parse_user_agent function."""

    def test_parse_chrome_user_agent(self) -> None:
        """Test parsing Chrome user agent."""
        ua = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/91.0.4472.124 Safari/537.36'
        )
        family, version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Chrome')
        self.assertEqual(version, '91.0')

    def test_parse_firefox_user_agent(self) -> None:
        """Test parsing Firefox user agent."""
        ua = (
            'Mozilla/5.0 (X11; Linux x86_64; rv:89.0) '
            'Gecko/20100101 Firefox/89.0'
        )
        family, version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Firefox')
        self.assertEqual(version, '89.0')

    def test_parse_safari_user_agent(self) -> None:
        """Test parsing Safari user agent."""
        ua = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) '
            'Version/14.1.1 Safari/605.1.15'
        )
        family, version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Safari')
        # Version comes from Safari/ part
        self.assertEqual(version, '605.1')

    def test_parse_edge_user_agent(self) -> None:
        """Test parsing Edge user agent."""
        ua = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59'
        )
        family, version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Edge')
        self.assertEqual(version, '91.0')

    def test_parse_opera_user_agent(self) -> None:
        """Test parsing Opera user agent."""
        ua = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/91.0.4472.124 Safari/537.36 OPR/77.0.4054.203'
        )
        # Note: This will match Chrome first since 'chrome/' appears
        # before 'opera/'
        family, _version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Chrome')

    def test_parse_none_user_agent(self) -> None:
        """Test parsing None user agent."""
        family, version = privacy.parse_user_agent(None)
        self.assertEqual(family, 'unknown')
        self.assertEqual(version, 'unknown')

    def test_parse_empty_user_agent(self) -> None:
        """Test parsing empty user agent."""
        family, version = privacy.parse_user_agent('')
        self.assertEqual(family, 'unknown')
        self.assertEqual(version, 'unknown')

    def test_parse_unknown_user_agent(self) -> None:
        """Test parsing unknown user agent."""
        family, version = privacy.parse_user_agent('CustomBot/1.0')
        self.assertEqual(family, 'unknown')
        self.assertEqual(version, 'unknown')

    def test_parse_malformed_version(self) -> None:
        """Test parsing user agent with malformed version."""
        ua = 'Mozilla/5.0 Chrome/'
        family, version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Chrome')
        self.assertEqual(version, 'unknown')

    def test_parse_single_digit_version(self) -> None:
        """Test parsing user agent with single digit version."""
        ua = 'Mozilla/5.0 Chrome/91'
        family, version = privacy.parse_user_agent(ua)
        self.assertEqual(family, 'Chrome')
        self.assertEqual(version, '91')


class SanitizeMetadataTestCase(unittest.TestCase):
    """Test cases for sanitize_metadata function."""

    def test_sanitize_email_field(self) -> None:
        """Test sanitization of email field."""
        metadata = {'endpoint': '/api/users', 'email': 'user@example.com'}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['endpoint'], '/api/users')
        self.assertEqual(sanitized['email'], '[REDACTED]')

    def test_sanitize_password_field(self) -> None:
        """Test sanitization of password field."""
        metadata = {'username': 'testuser', 'password': 'secret123'}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['username'], 'testuser')
        self.assertEqual(sanitized['password'], '[REDACTED]')

    def test_sanitize_token_field(self) -> None:
        """Test sanitization of token field."""
        metadata = {'action': 'login', 'auth_token': 'abc123'}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['action'], 'login')
        self.assertEqual(sanitized['auth_token'], '[REDACTED]')

    def test_sanitize_api_key_field(self) -> None:
        """Test sanitization of api_key field."""
        metadata = {'service': 'api', 'api_key': 'key123'}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['service'], 'api')
        self.assertEqual(sanitized['api_key'], '[REDACTED]')

    def test_sanitize_secret_field(self) -> None:
        """Test sanitization of secret field."""
        metadata = {'app': 'myapp', 'client_secret': 'secretvalue'}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['app'], 'myapp')
        self.assertEqual(sanitized['client_secret'], '[REDACTED]')

    def test_sanitize_nested_dict(self) -> None:
        """Test sanitization of nested dictionary."""
        metadata = {
            'user': {'name': 'John', 'email': 'john@example.com'},
            'status': 200,
        }
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['status'], 200)
        self.assertEqual(sanitized['user']['name'], 'John')
        self.assertEqual(sanitized['user']['email'], '[REDACTED]')

    def test_sanitize_case_insensitive(self) -> None:
        """Test that sanitization is case-insensitive."""
        metadata = {'EMAIL': 'test@example.com', 'Password': 'pass123'}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['EMAIL'], '[REDACTED]')
        self.assertEqual(sanitized['Password'], '[REDACTED]')

    def test_sanitize_partial_match(self) -> None:
        """Test that partial keyword matches are redacted."""
        metadata = {
            'user_email': 'test@example.com',
            'api_token_value': 'token123',
        }
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['user_email'], '[REDACTED]')
        self.assertEqual(sanitized['api_token_value'], '[REDACTED]')

    def test_sanitize_no_pii(self) -> None:
        """Test sanitization when no PII is present."""
        metadata = {'endpoint': '/api/status', 'status_code': 200}
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['endpoint'], '/api/status')
        self.assertEqual(sanitized['status_code'], 200)

    def test_sanitize_empty_dict(self) -> None:
        """Test sanitization of empty dictionary."""
        result = privacy.sanitize_metadata({})
        sanitized = json.loads(result)
        self.assertEqual(sanitized, {})

    def test_sanitize_string_values_with_pii_keywords(self) -> None:
        """Test sanitization of string values containing PII keywords."""
        metadata = {
            'message': 'User password reset requested',
            'action': 'reset',
        }
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['message'], '[REDACTED]')
        self.assertEqual(sanitized['action'], 'reset')

    def test_sanitize_preserves_non_string_types(self) -> None:
        """Test that non-string, non-dict types are preserved."""
        metadata = {
            'count': 42,
            'active': True,
            'ratio': 3.14,
            'items': [1, 2, 3],
        }
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['count'], 42)
        self.assertEqual(sanitized['active'], True)
        self.assertEqual(sanitized['ratio'], 3.14)
        self.assertEqual(sanitized['items'], [1, 2, 3])

    def test_sanitize_multiple_pii_fields(self) -> None:
        """Test sanitization with multiple PII fields."""
        metadata = {
            'email': 'user@example.com',
            'password': 'secret',
            'token': 'abc123',
            'api_key': 'key456',
            'safe_field': 'public data',
        }
        result = privacy.sanitize_metadata(metadata)
        sanitized = json.loads(result)
        self.assertEqual(sanitized['email'], '[REDACTED]')
        self.assertEqual(sanitized['password'], '[REDACTED]')
        self.assertEqual(sanitized['token'], '[REDACTED]')
        self.assertEqual(sanitized['api_key'], '[REDACTED]')
        self.assertEqual(sanitized['safe_field'], 'public data')
