import unittest
from unittest import mock


class ImbiVersionTestCase(unittest.TestCase):
    """Test cases for imbi package version handling."""

    def test_version_from_metadata(self) -> None:
        """Test version is retrieved from package metadata."""
        # This test verifies the version exists when package is installed
        import imbi

        self.assertIsInstance(imbi.version, str)
        self.assertNotEqual(imbi.version, '')

    def test_version_fallback(self) -> None:
        """Test version falls back to 0.0.0 when package not found."""
        # Mock metadata.version to raise PackageNotFoundError
        with mock.patch('importlib.metadata.version') as mock_version:
            # Import the module fresh to trigger the exception handler
            import importlib
            from importlib import metadata

            mock_version.side_effect = metadata.PackageNotFoundError()

            # Reload the module to test the exception path
            import imbi

            importlib.reload(imbi)

            # Should fall back to 0.0.0
            self.assertEqual(imbi.version, '0.0.0')

            # Reset mock for other tests
            mock_version.side_effect = None
