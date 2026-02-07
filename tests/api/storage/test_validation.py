"""Tests for upload file validation."""

import unittest
from unittest import mock

from imbi_common import settings

from imbi_api.storage import validation


class ValidateUploadTestCase(unittest.TestCase):
    """Test cases for validate_upload."""

    def setUp(self) -> None:
        self.settings = settings.Storage(
            max_file_size=1024,
            allowed_content_types=[
                'image/jpeg',
                'image/png',
                'image/svg+xml',
                'application/pdf',
            ],
        )

    def test_valid_jpeg(self) -> None:
        """Test that a valid JPEG passes validation."""
        # Minimal JPEG header (FFD8FF)
        data = b'\xff\xd8\xff\xe0' + b'\x00\x10JFIF\x00' + b'\x00' * 100
        with mock.patch(
            'imbi_api.storage.validation.filetype.guess'
        ) as mock_guess:
            mock_guess.return_value = mock.Mock(
                mime='image/jpeg',
            )
            validation.validate_upload(
                data,
                'image/jpeg',
                self.settings,
            )

    def test_disallowed_content_type(self) -> None:
        """Test that a disallowed content type raises."""
        with self.assertRaises(
            validation.UploadValidationError,
        ) as ctx:
            validation.validate_upload(
                b'data',
                'text/plain',
                self.settings,
            )
        self.assertIn('not allowed', str(ctx.exception))

    def test_file_too_large(self) -> None:
        """Test that an oversized file raises."""
        data = b'\x00' * 2048  # Exceeds 1024 byte limit
        with self.assertRaises(
            validation.UploadValidationError,
        ) as ctx:
            validation.validate_upload(
                data,
                'image/svg+xml',
                self.settings,
            )
        self.assertIn('exceeds maximum', str(ctx.exception))

    def test_empty_file_with_magic_type(self) -> None:
        """Test that an empty file with a magic-byte type raises."""
        with self.assertRaises(
            validation.UploadValidationError,
        ) as ctx:
            validation.validate_upload(
                b'',
                'image/jpeg',
                self.settings,
            )
        self.assertIn('empty', str(ctx.exception))

    def test_magic_byte_mismatch(self) -> None:
        """Test that mismatched magic bytes raise."""
        data = b'\x89PNG' + b'\x00' * 100
        with mock.patch(
            'imbi_api.storage.validation.filetype.guess'
        ) as mock_guess:
            mock_guess.return_value = mock.Mock(
                mime='image/png',
            )
            with self.assertRaises(
                validation.UploadValidationError,
            ) as ctx:
                validation.validate_upload(
                    data,
                    'image/jpeg',
                    self.settings,
                )
            self.assertIn('detected as', str(ctx.exception))

    def test_undetectable_magic_bytes(self) -> None:
        """Test that undetectable magic bytes raise."""
        data = b'\x00' * 100
        with mock.patch(
            'imbi_api.storage.validation.filetype.guess',
            return_value=None,
        ):
            with self.assertRaises(
                validation.UploadValidationError,
            ) as ctx:
                validation.validate_upload(
                    data,
                    'image/jpeg',
                    self.settings,
                )
            self.assertIn(
                'Unable to detect',
                str(ctx.exception),
            )

    def test_svg_skips_magic_byte_check(self) -> None:
        """Test that SVG files skip magic-byte validation."""
        data = b'<svg>test</svg>'
        # Should not raise even though no magic bytes
        validation.validate_upload(
            data,
            'image/svg+xml',
            self.settings,
        )

    def test_uses_default_settings(self) -> None:
        """Test that default settings are used when none provided."""
        with mock.patch(
            'imbi_api.storage.validation.filetype.guess'
        ) as mock_guess:
            mock_guess.return_value = mock.Mock(
                mime='image/png',
            )
            # Should not raise with default settings and small file
            data = b'\x89PNG' + b'\x00' * 50
            validation.validate_upload(data, 'image/png')
