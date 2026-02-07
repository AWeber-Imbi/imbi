"""Object storage module for file uploads.

Provides S3-compatible object storage for uploading, downloading,
and serving files. Uses presigned URLs for efficient file delivery.
"""

import logging

from . import client

LOGGER = logging.getLogger(__name__)

__all__ = [
    'aclose',
    'delete',
    'download',
    'initialize',
    'presigned_url',
    'upload',
]


async def initialize() -> None:
    """Initialize the storage module.

    Creates the StorageClient singleton and ensures the configured
    S3 bucket exists.

    """
    LOGGER.info('Initializing storage module')
    storage_client = client.StorageClient.get_instance()
    await storage_client.initialize()
    LOGGER.info('Storage module initialized')


async def aclose() -> None:
    """Clean up storage module resources."""
    LOGGER.info('Closing storage module')
    if client.StorageClient._instance is not None:
        await client.StorageClient._instance.aclose()
    client.StorageClient._instance = None
    LOGGER.info('Storage module closed')


async def upload(
    key: str,
    data: bytes,
    content_type: str,
) -> None:
    """Upload bytes to S3.

    Args:
        key: S3 object key
        data: File content as bytes
        content_type: MIME type of the file

    """
    storage_client = client.StorageClient.get_instance()
    await storage_client.upload(key, data, content_type)


async def download(key: str) -> bytes:
    """Download bytes from S3.

    Args:
        key: S3 object key

    Returns:
        File content as bytes

    """
    storage_client = client.StorageClient.get_instance()
    return await storage_client.download(key)


async def delete(key: str) -> None:
    """Delete an object from S3.

    Args:
        key: S3 object key

    """
    storage_client = client.StorageClient.get_instance()
    await storage_client.delete(key)


async def presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for an S3 object.

    Args:
        key: S3 object key
        expires_in: URL expiration time in seconds (default: 1 hour)

    Returns:
        Presigned URL string

    """
    storage_client = client.StorageClient.get_instance()
    return await storage_client.presigned_url(key, expires_in)
