"""Tests for storage module exports."""

import unittest

from imbi.api import storage
from imbi.api.storage.client import StorageClient
from imbi.api.storage.dependencies import InjectStorageClient


class StorageModuleTestCase(unittest.TestCase):
    """Test cases for storage module public API."""

    def test_exports_storage_client(self) -> None:
        self.assertIs(storage.StorageClient, StorageClient)

    def test_exports_inject_type(self) -> None:
        self.assertIs(
            storage.InjectStorageClient,
            InjectStorageClient,
        )
