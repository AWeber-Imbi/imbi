import importlib
import importlib.metadata
import sys
import unittest
from typing import TYPE_CHECKING
from unittest import mock

if TYPE_CHECKING:
    import types


class VersionTests(unittest.TestCase):
    def _reimport(self) -> types.ModuleType:
        sys.modules.pop('imbi.assistant', None)
        return importlib.import_module('imbi.assistant')

    def test_version_is_string(self) -> None:
        mod = self._reimport()
        self.assertIsInstance(mod.version, str)

    def test_version_info_is_list(self) -> None:
        mod = self._reimport()
        self.assertIsInstance(mod.version_info, list)

    def test_version_info_has_integers(self) -> None:
        mod = self._reimport()
        for part in mod.version_info[:3]:
            self.assertIsInstance(part, int)

    def test_fallback_when_package_not_found(self) -> None:
        with mock.patch(
            'importlib.metadata.version',
            side_effect=importlib.metadata.PackageNotFoundError(
                'imbi-assistant'
            ),
        ):
            mod = self._reimport()

        self.assertEqual('0.0.0', mod.version)
        self.assertEqual([0, 0, 0], mod.version_info)

    def test_prerelease_version_parsing(self) -> None:
        with mock.patch(
            'importlib.metadata.version',
            return_value='1.2.3rc1',
        ):
            mod = self._reimport()

        self.assertEqual('1.2.3rc1', mod.version)
        self.assertEqual([1, 2, 3, 'rc1'], mod.version_info)
