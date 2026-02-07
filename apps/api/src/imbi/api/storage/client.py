"""S3 client singleton for object storage operations."""

import asyncio
import logging
import typing

import aioboto3
from botocore import exceptions as botocore_exceptions
from imbi_common import settings

LOGGER = logging.getLogger(__name__)


class StorageClient:
    """Singleton S3 client for object storage operations.

    Uses aioboto3 for native async S3 operations. Supports both
    real AWS S3 and S3-compatible services like LocalStack.

    """

    _instance: typing.ClassVar['StorageClient | None'] = None
    _lock: typing.ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self) -> None:
        self._settings = settings.Storage()
        self._session = aioboto3.Session(
            aws_access_key_id=self._settings.access_key or None,
            aws_secret_access_key=self._settings.secret_key or None,
            region_name=self._settings.region,
        )
        self._initialized = False

    @classmethod
    def get_instance(cls) -> 'StorageClient':
        """Get the singleton StorageClient instance.

        Returns:
            The singleton StorageClient instance.

        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> None:
        """Initialize the storage client and ensure the bucket exists.

        Raises:
            Exception: If S3 connection or bucket creation fails.

        """
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            if self._settings.create_bucket_on_init:
                await self._ensure_bucket()

            self._initialized = True

    async def aclose(self) -> None:
        """Clean up storage client resources."""
        async with self._lock:
            self._initialized = False
            LOGGER.debug('Storage client closed')

    async def upload(
        self,
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
        async with self._s3_client() as s3:
            await s3.put_object(
                Bucket=self._settings.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        LOGGER.debug('Uploaded %s (%d bytes)', key, len(data))

    async def download(self, key: str) -> bytes:
        """Download bytes from S3.

        Args:
            key: S3 object key

        Returns:
            File content as bytes

        """
        async with self._s3_client() as s3:
            response = await s3.get_object(
                Bucket=self._settings.bucket,
                Key=key,
            )
            async with response['Body'] as body:
                data: bytes = await body.read()
        LOGGER.debug('Downloaded %s (%d bytes)', key, len(data))
        return data

    async def delete(self, key: str) -> None:
        """Delete an object from S3.

        Args:
            key: S3 object key

        """
        async with self._s3_client() as s3:
            await s3.delete_object(
                Bucket=self._settings.bucket,
                Key=key,
            )
        LOGGER.debug('Deleted %s', key)

    async def presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        """Generate a presigned GET URL for an S3 object.

        Args:
            key: S3 object key
            expires_in: URL expiration time in seconds

        Returns:
            Presigned URL string

        """
        async with self._s3_client() as s3:
            url: str = await s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self._settings.bucket,
                    'Key': key,
                },
                ExpiresIn=expires_in,
            )
        return url

    def _s3_client(self) -> typing.Any:
        """Create an S3 client context manager.

        Returns:
            Async context manager yielding an S3 client.

        """
        kwargs: dict[str, typing.Any] = {}
        if self._settings.endpoint_url:
            kwargs['endpoint_url'] = self._settings.endpoint_url
        return self._session.client('s3', **kwargs)

    async def _ensure_bucket(self) -> None:
        """Create the S3 bucket if it does not exist."""
        async with self._s3_client() as s3:
            try:
                await s3.head_bucket(Bucket=self._settings.bucket)
                LOGGER.debug(
                    'Bucket %s already exists',
                    self._settings.bucket,
                )
            except botocore_exceptions.ClientError:
                params: dict[str, typing.Any] = {
                    'Bucket': self._settings.bucket,
                }
                if (
                    self._settings.region
                    and self._settings.region != 'us-east-1'
                ):
                    params['CreateBucketConfiguration'] = {
                        'LocationConstraint': self._settings.region,
                    }
                await s3.create_bucket(**params)
                LOGGER.info('Created bucket %s', self._settings.bucket)
