"""Tests for StorageClient with mocked S3."""

import unittest
from unittest import mock

from imbi_api.storage import client


class StorageClientSingletonTestCase(unittest.TestCase):
    """Test cases for StorageClient singleton pattern."""

    def setUp(self) -> None:
        client.StorageClient._instance = None

    def tearDown(self) -> None:
        client.StorageClient._instance = None

    def test_get_instance_creates_singleton(self) -> None:
        """Test that get_instance creates a singleton."""
        instance1 = client.StorageClient.get_instance()
        instance2 = client.StorageClient.get_instance()
        self.assertIs(instance1, instance2)

    def test_get_instance_returns_new_after_reset(self) -> None:
        """Test that resetting creates a new instance."""
        instance1 = client.StorageClient.get_instance()
        client.StorageClient._instance = None
        instance2 = client.StorageClient.get_instance()
        self.assertIsNot(instance1, instance2)


class StorageClientOperationsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for StorageClient S3 operations."""

    async def asyncSetUp(self) -> None:
        client.StorageClient._instance = None
        self.client = client.StorageClient.get_instance()

    async def asyncTearDown(self) -> None:
        client.StorageClient._instance = None

    async def test_initialize_creates_bucket(self) -> None:
        """Test that initialize creates the bucket."""
        mock_s3 = mock.AsyncMock()
        mock_s3.head_bucket.side_effect = (
            client.botocore_exceptions.ClientError(
                {'Error': {'Code': '404'}},
                'HeadBucket',
            )
        )

        with mock.patch.object(
            self.client,
            '_s3_client',
            return_value=_async_ctx(mock_s3),
        ):
            await self.client.initialize()

        mock_s3.create_bucket.assert_called_once()

    async def test_initialize_skips_existing_bucket(self) -> None:
        """Test that initialize skips if bucket exists."""
        mock_s3 = mock.AsyncMock()

        with mock.patch.object(
            self.client,
            '_s3_client',
            return_value=_async_ctx(mock_s3),
        ):
            await self.client.initialize()

        mock_s3.create_bucket.assert_not_called()

    async def test_upload(self) -> None:
        """Test uploading bytes to S3."""
        mock_s3 = mock.AsyncMock()

        with mock.patch.object(
            self.client,
            '_s3_client',
            return_value=_async_ctx(mock_s3),
        ):
            await self.client.upload(
                'test/key',
                b'data',
                'text/plain',
            )

        mock_s3.put_object.assert_called_once_with(
            Bucket=self.client._settings.bucket,
            Key='test/key',
            Body=b'data',
            ContentType='text/plain',
        )

    async def test_download(self) -> None:
        """Test downloading bytes from S3."""
        mock_body = mock.AsyncMock()
        mock_body.read.return_value = b'file-data'
        mock_body.__aenter__.return_value = mock_body
        mock_body.__aexit__.return_value = None
        mock_s3 = mock.AsyncMock()
        mock_s3.get_object.return_value = {'Body': mock_body}

        with mock.patch.object(
            self.client,
            '_s3_client',
            return_value=_async_ctx(mock_s3),
        ):
            result = await self.client.download('test/key')

        self.assertEqual(result, b'file-data')

    async def test_delete(self) -> None:
        """Test deleting an object from S3."""
        mock_s3 = mock.AsyncMock()

        with mock.patch.object(
            self.client,
            '_s3_client',
            return_value=_async_ctx(mock_s3),
        ):
            await self.client.delete('test/key')

        mock_s3.delete_object.assert_called_once_with(
            Bucket=self.client._settings.bucket,
            Key='test/key',
        )

    async def test_presigned_url(self) -> None:
        """Test generating a presigned URL."""
        mock_s3 = mock.AsyncMock()
        mock_s3.generate_presigned_url.return_value = (
            'https://s3.example.com/signed'
        )

        with mock.patch.object(
            self.client,
            '_s3_client',
            return_value=_async_ctx(mock_s3),
        ):
            url = await self.client.presigned_url(
                'test/key',
                3600,
            )

        self.assertEqual(url, 'https://s3.example.com/signed')
        mock_s3.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={
                'Bucket': self.client._settings.bucket,
                'Key': 'test/key',
            },
            ExpiresIn=3600,
        )

    async def test_aclose(self) -> None:
        """Test that aclose resets initialization state."""
        self.client._initialized = True
        await self.client.aclose()
        self.assertFalse(self.client._initialized)


class _AsyncContextManager:
    """Helper to wrap a mock as an async context manager."""

    def __init__(self, value: mock.AsyncMock) -> None:
        self._value = value

    async def __aenter__(self) -> mock.AsyncMock:
        return self._value

    async def __aexit__(self, *args: object) -> None:
        pass


def _async_ctx(value: mock.AsyncMock) -> _AsyncContextManager:
    return _AsyncContextManager(value)
