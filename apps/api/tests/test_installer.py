"""Verify the runtime plugin installer hardening.

Targets the input-validation surface added in fix/plugin-installer-hardening:
package-name allowlist, version-string shape, and the resulting uv pip
argv (``--no-deps``, pinned ``--index-url``).
"""

import unittest
from unittest import mock

from imbi.api.plugins import installer


class ValidateNameTestCase(unittest.TestCase):
    def test_accepts_imbi_plugin_prefix(self) -> None:
        self.assertEqual(
            installer._validate_name('imbi-plugin-github'),
            'imbi-plugin-github',
        )

    def test_accepts_letters_digits_underscores_hyphens(self) -> None:
        self.assertEqual(
            installer._validate_name('imbi-plugin-aws_iam_ic-2'),
            'imbi-plugin-aws_iam_ic-2',
        )

    def test_rejects_bare_pypi_name(self) -> None:
        with self.assertRaisesRegex(installer.InstallError, 'allowlist'):
            installer._validate_name('requests')

    def test_rejects_uppercase(self) -> None:
        with self.assertRaisesRegex(installer.InstallError, 'allowlist'):
            installer._validate_name('Imbi-Plugin-GitHub')

    def test_rejects_index_url_injection(self) -> None:
        with self.assertRaisesRegex(installer.InstallError, 'allowlist'):
            installer._validate_name('imbi-plugin-x --index-url=http://evil/')

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(installer.InstallError, 'allowlist'):
            installer._validate_name('../etc/passwd')


class ValidateVersionTestCase(unittest.TestCase):
    def test_accepts_simple_release(self) -> None:
        self.assertEqual(installer._validate_version('1.2.3'), '1.2.3')

    def test_accepts_pre_release(self) -> None:
        self.assertEqual(installer._validate_version('1.2.3rc1'), '1.2.3rc1')

    def test_accepts_local_segment(self) -> None:
        self.assertEqual(
            installer._validate_version('1.2.3+local.tag'),
            '1.2.3+local.tag',
        )

    def test_none_passes_through(self) -> None:
        self.assertIsNone(installer._validate_version(None))

    def test_rejects_whitespace(self) -> None:
        with self.assertRaisesRegex(installer.InstallError, 'PEP 440'):
            installer._validate_version('1.2.3 --index-url=http://evil/')

    def test_rejects_shell_metacharacters(self) -> None:
        with self.assertRaisesRegex(installer.InstallError, 'PEP 440'):
            installer._validate_version('1.2.3;rm -rf /')


class InstallPackageArgvTestCase(unittest.IsolatedAsyncioTestCase):
    """Confirm the uv invocation pins --index-url and includes --no-deps."""

    async def test_install_uses_no_deps_and_pinned_index(self) -> None:
        fake_proc = mock.AsyncMock()
        fake_proc.communicate.return_value = (b'installed', b'')
        fake_proc.returncode = 0
        with (
            mock.patch.object(
                installer.asyncio,
                'create_subprocess_exec',
                new=mock.AsyncMock(return_value=fake_proc),
            ) as spawn,
            mock.patch.object(
                installer, 'reload_plugins', return_value=mock.MagicMock()
            ),
        ):
            await installer.install_package('imbi-plugin-github', '1.2.3')

        spawn.assert_awaited_once()
        argv = spawn.await_args.args
        self.assertEqual(
            argv[:5], ('uv', 'pip', 'install', '--no-deps', '--index-url')
        )
        self.assertEqual(argv[6], 'imbi-plugin-github==1.2.3')

    async def test_install_rejects_non_allowlisted_name(self) -> None:
        with self.assertRaises(installer.InstallError):
            await installer.install_package('requests')

    async def test_install_rejects_malformed_version(self) -> None:
        with self.assertRaises(installer.InstallError):
            await installer.install_package(
                'imbi-plugin-x', '1.0 --index-url=http://evil/'
            )

    async def test_uninstall_rejects_non_allowlisted_name(self) -> None:
        with self.assertRaises(installer.InstallError):
            await installer.uninstall_package('requests')
