import importlib
import sys
import unittest
from unittest import mock


class VersionTests(unittest.TestCase):
    def _reimport(self) -> None:
        sys.modules.pop('imbi_assistant', None)
        importlib.import_module('imbi_assistant')

    def test_version_is_string(self) -> None:
        import imbi_assistant

        self.assertIsInstance(imbi_assistant.version, str)

    def test_version_info_is_list(self) -> None:
        import imbi_assistant

        self.assertIsInstance(imbi_assistant.version_info, list)

    def test_version_info_has_integers(self) -> None:
        import imbi_assistant

        for part in imbi_assistant.version_info[:3]:
            self.assertIsInstance(part, int)

    def test_fallback_when_package_not_found(self) -> None:
        with mock.patch(
            'importlib.metadata.version',
            side_effect=importlib.metadata.PackageNotFoundError(
                'imbi-assistant'
            ),
        ):
            self._reimport()

        import imbi_assistant

        self.assertEqual('0.0.0', imbi_assistant.version)
        self.assertEqual([0, 0, 0], imbi_assistant.version_info)

    def test_prerelease_version_parsing(self) -> None:
        with mock.patch(
            'importlib.metadata.version',
            return_value='1.2.3rc1',
        ):
            self._reimport()

        import imbi_assistant

        self.assertEqual('1.2.3rc1', imbi_assistant.version)
        self.assertEqual([1, 2, 3, 'rc1'], imbi_assistant.version_info)
