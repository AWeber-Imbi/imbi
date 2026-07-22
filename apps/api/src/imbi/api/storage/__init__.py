"""Object storage module for file uploads.

Provides S3-compatible object storage for uploading, downloading,
and serving files. Uses presigned URLs for efficient file delivery.
"""

from .client import StorageClient
from .dependencies import InjectStorageClient

__all__ = [
    'InjectStorageClient',
    'StorageClient',
]
