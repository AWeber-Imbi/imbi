import unittest

import pydantic

from imbi import settings


class Neo4jSettingsTestCase(unittest.TestCase):
    """Test cases for Neo4j settings."""

    def test_default_settings(self) -> None:
        """Test Neo4j settings with explicit defaults."""
        # Provide explicit URL to avoid environment interference
        neo4j = settings.Neo4j(url=pydantic.AnyUrl('neo4j://localhost:7687'))
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')
        self.assertIsNone(neo4j.user)
        self.assertIsNone(neo4j.password)
        self.assertEqual(neo4j.database, 'neo4j')
        self.assertTrue(neo4j.keep_alive)
        self.assertEqual(neo4j.liveness_check_timeout, 60)
        self.assertEqual(neo4j.max_connection_lifetime, 300)

    def test_url_with_username_and_password(self) -> None:
        """Test extracting username and password from URL."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://testuser:testpass@localhost:7687')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'testuser')
        self.assertEqual(neo4j.password, 'testpass')

        # URL should be cleaned (no credentials)
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')
        self.assertIsNone(neo4j.url.username)
        self.assertIsNone(neo4j.url.password)

    def test_url_with_only_username(self) -> None:
        """Test extracting only username from URL."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://testuser@localhost:7687')
        )

        # Username should be extracted
        self.assertEqual(neo4j.user, 'testuser')
        self.assertIsNone(neo4j.password)

        # URL should be cleaned
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')

    def test_url_with_credentials_and_path(self) -> None:
        """Test URL with credentials and path component."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:pass@localhost:7687/database')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should preserve path but remove credentials
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687/database')

    def test_explicit_user_password_not_overridden(self) -> None:
        """Test that explicit user/password are not overridden by URL."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://urluser:urlpass@localhost:7687'),
            user='explicituser',
            password='explicitpass',
        )

        # Explicit credentials should take precedence
        self.assertEqual(neo4j.user, 'explicituser')
        self.assertEqual(neo4j.password, 'explicitpass')

        # URL should still be cleaned
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')

    def test_url_without_credentials(self) -> None:
        """Test URL without embedded credentials."""
        neo4j = settings.Neo4j(url=pydantic.AnyUrl('neo4j://remotehost:7687'))

        # No credentials should be set
        self.assertIsNone(neo4j.user)
        self.assertIsNone(neo4j.password)

        # URL should remain unchanged
        self.assertEqual(str(neo4j.url), 'neo4j://remotehost:7687')

    def test_url_with_different_port(self) -> None:
        """Test URL with non-default port."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:pass@example.com:9999')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should preserve custom port
        self.assertEqual(str(neo4j.url), 'neo4j://example.com:9999')

    def test_url_with_special_characters_in_password(self) -> None:
        """Test URL with special characters in password."""
        # URL-encoded password with special chars
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:p%40ss%23word@localhost:7687')
        )

        # Password should be decoded
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'p@ss#word')

        # URL should be cleaned
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')

    def test_bolt_scheme(self) -> None:
        """Test with bolt:// scheme."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('bolt://user:pass@localhost:7687')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should preserve bolt scheme
        self.assertEqual(str(neo4j.url), 'bolt://localhost:7687')


class ServerConfigSettingsTestCase(unittest.TestCase):
    """Test cases for ServerConfig settings."""

    def test_default_settings(self) -> None:
        """Test ServerConfig settings with defaults."""
        config = settings.ServerConfig()
        self.assertEqual(config.environment, 'development')
        self.assertEqual(config.host, 'localhost')
        self.assertEqual(config.port, 8000)

    def test_custom_settings(self) -> None:
        """Test ServerConfig with custom values."""
        config = settings.ServerConfig(
            environment='production', host='0.0.0.0', port=9000
        )
        self.assertEqual(config.environment, 'production')
        self.assertEqual(config.host, '0.0.0.0')
        self.assertEqual(config.port, 9000)
