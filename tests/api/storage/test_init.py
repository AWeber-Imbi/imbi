"""Tests for storage module-level convenience functions."""

import unittest
from unittest import mock

from imbi_api import storage
from imbi_api.storage import client


class StorageModuleTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for storage module functions."""

    async def asyncSetUp(self) -> None:
        client.StorageClient._instance = None

    async def asyncTearDown(self) -> None:
        client.StorageClient._instance = None

    async def test_initialize(self) -> None:
        """Test that initialize delegates to the client."""
        mock_client = mock.AsyncMock()
        with mock.patch.object(
            client.StorageClient,
            'get_instance',
            return_value=mock_client,
        ):
            await storage.initialize()
        mock_client.initialize.assert_awaited_once()

    async def test_aclose_with_instance(self) -> None:
        """Test aclose when an instance exists."""
        mock_instance = mock.AsyncMock()
        client.StorageClient._instance = mock_instance
        await storage.aclose()
        mock_instance.aclose.assert_awaited_once()
        self.assertIsNone(client.StorageClient._instance)

    async def test_aclose_without_instance(self) -> None:
        """Test aclose when no instance exists."""
        client.StorageClient._instance = None
        await storage.aclose()
        self.assertIsNone(client.StorageClient._instance)

    async def test_upload(self) -> None:
        """Test that upload delegates to the client."""
        mock_client = mock.AsyncMock()
        with mock.patch.object(
            client.StorageClient,
            'get_instance',
            return_value=mock_client,
        ):
            await storage.upload(
                'test/key',
                b'data',
                'text/plain',
            )
        mock_client.upload.assert_awaited_once_with(
            'test/key',
            b'data',
            'text/plain',
        )

    async def test_download(self) -> None:
        """Test that download delegates and returns result."""
        mock_client = mock.AsyncMock()
        mock_client.download.return_value = b'file-data'
        with mock.patch.object(
            client.StorageClient,
            'get_instance',
            return_value=mock_client,
        ):
            result = await storage.download('test/key')
        self.assertEqual(result, b'file-data')
        mock_client.download.assert_awaited_once_with('test/key')

    async def test_delete(self) -> None:
        """Test that delete delegates to the client."""
        mock_client = mock.AsyncMock()
        with mock.patch.object(
            client.StorageClient,
            'get_instance',
            return_value=mock_client,
        ):
            await storage.delete('test/key')
        mock_client.delete.assert_awaited_once_with('test/key')

    async def test_presigned_url(self) -> None:
        """Test that presigned_url delegates and returns."""
        mock_client = mock.AsyncMock()
        mock_client.presigned_url.return_value = (
            'https://s3.example.com/signed'
        )
        with mock.patch.object(
            client.StorageClient,
            'get_instance',
            return_value=mock_client,
        ):
            url = await storage.presigned_url('test/key', 7200)
        self.assertEqual(url, 'https://s3.example.com/signed')
        mock_client.presigned_url.assert_awaited_once_with(
            'test/key',
            7200,
        )

    async def test_presigned_url_default_expiry(self) -> None:
        """Test presigned_url uses default 3600s expiry."""
        mock_client = mock.AsyncMock()
        mock_client.presigned_url.return_value = (
            'https://s3.example.com/signed'
        )
        with mock.patch.object(
            client.StorageClient,
            'get_instance',
            return_value=mock_client,
        ):
            await storage.presigned_url('test/key')
        mock_client.presigned_url.assert_awaited_once_with(
            'test/key',
            3600,
        )
