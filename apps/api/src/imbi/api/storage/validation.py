"""File validation for uploads."""

import logging

import filetype
from imbi_common import settings

LOGGER = logging.getLogger(__name__)


class UploadValidationError(Exception):
    """Raised when an uploaded file fails validation."""


# Content types that support magic-byte detection
_MAGIC_BYTE_TYPES = frozenset(
    {
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'application/pdf',
    }
)


def validate_upload(
    data: bytes,
    declared_content_type: str,
    storage_settings: settings.Storage | None = None,
) -> None:
    """Validate an uploaded file.

    Checks content type against the allow list, file size against
    the configured maximum, and verifies magic bytes match the
    declared content type for binary formats.

    Args:
        data: File content as bytes
        declared_content_type: MIME type declared by the client
        storage_settings: Storage settings (uses defaults if None)

    Raises:
        UploadValidationError: If validation fails.

    """
    if storage_settings is None:
        storage_settings = settings.Storage()

    _validate_content_type(declared_content_type, storage_settings)
    _validate_file_size(data, storage_settings)
    _validate_magic_bytes(data, declared_content_type)


def _validate_content_type(
    content_type: str,
    storage_settings: settings.Storage,
) -> None:
    """Check that the content type is in the allow list."""
    if content_type not in storage_settings.allowed_content_types:
        raise UploadValidationError(
            f'Content type {content_type!r} is not allowed. '
            f'Allowed types: {storage_settings.allowed_content_types}'
        )


def _validate_file_size(
    data: bytes,
    storage_settings: settings.Storage,
) -> None:
    """Check that the file size is within limits."""
    if len(data) > storage_settings.max_file_size:
        max_mb = storage_settings.max_file_size / (1024 * 1024)
        raise UploadValidationError(
            f'File size {len(data)} bytes exceeds maximum of {max_mb:.0f} MB'
        )


def _validate_magic_bytes(
    data: bytes,
    declared_content_type: str,
) -> None:
    """Verify magic bytes match the declared content type.

    Only checks binary formats that have reliable magic byte
    signatures. Text-based formats like SVG are skipped.

    """
    if declared_content_type not in _MAGIC_BYTE_TYPES:
        return

    if not data:
        raise UploadValidationError('File is empty')

    detected = filetype.guess(data)
    if detected is None:
        raise UploadValidationError(
            f'Unable to detect file type from content; '
            f'expected {declared_content_type!r}'
        )

    if detected.mime != declared_content_type:
        raise UploadValidationError(
            f'File content detected as {detected.mime!r} '
            f'but declared as {declared_content_type!r}'
        )
