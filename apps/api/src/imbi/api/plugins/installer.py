"""Runtime plugin installation via uv pip.

Plugin installation invokes ``uv pip install`` against a package name
supplied by the caller. To keep that surface narrow we:

* allow only package names matching ``^imbi-plugin-[a-z0-9_-]+$`` — no
  general PyPI specifiers, no ``pkg --index-url=…`` injection;
* require the version string (when provided) to match a normal PEP-440
  release shape so it cannot smuggle arguments through the spec;
* pin the index URL via ``IMBI_PLUGINS_INDEX_URL`` (defaults to PyPI)
  rather than inheriting whatever the host environment configured;
* pass ``--no-deps`` so installation can never pull transitive
  packages that aren't themselves allowlisted.
"""

import asyncio
import logging
import os
import re

from imbi.common.plugins.registry import (
    LoadResult,
    reload_plugins,
)

LOGGER = logging.getLogger(__name__)

_INSTALL_TIMEOUT = int(os.environ.get('IMBI_PLUGINS_INSTALL_TIMEOUT', '120'))
_INSTALL_ENABLED = (
    os.environ.get('IMBI_PLUGINS_INSTALL_ENABLED', 'true').lower() != 'false'
)
_INDEX_URL = os.environ.get(
    'IMBI_PLUGINS_INDEX_URL',
    'https://pypi.org/simple',
)

_PACKAGE_NAME = re.compile(r'^imbi-plugin-[a-z0-9_-]+$')
# Lenient PEP 440 release-segment match — `1`, `1.2`, `1.2.3`,
# `1.2.3.post4`, `1.2.3a1`, `1.2.3rc2`, `1.2.3+local.tag`. Rejects
# whitespace and shell metacharacters that could change the meaning
# of the resulting spec passed to uv.
_VERSION = re.compile(r'^[A-Za-z0-9.+!_-]+$')


class InstallError(Exception):
    """Raised when uv pip install fails."""


def _validate_name(name: str) -> str:
    if not _PACKAGE_NAME.match(name):
        raise InstallError(
            f'Refusing to install package {name!r}: not in the '
            "'imbi-plugin-*' allowlist"
        )
    return name


def _validate_version(version: str | None) -> str | None:
    if version is None:
        return None
    if not _VERSION.match(version):
        raise InstallError(
            f'Refusing to install with version {version!r}: '
            'must match PEP 440 release shape'
        )
    return version


async def install_package(name: str, version: str | None = None) -> LoadResult:
    """Install a plugin package at runtime via uv pip."""
    if not _INSTALL_ENABLED:
        raise InstallError(
            'Runtime plugin installation is disabled '
            '(IMBI_PLUGINS_INSTALL_ENABLED=false)'
        )
    name = _validate_name(name)
    version = _validate_version(version)
    spec = f'{name}=={version}' if version else name
    proc = await asyncio.create_subprocess_exec(
        'uv',
        'pip',
        'install',
        '--no-deps',
        '--index-url',
        _INDEX_URL,
        spec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_INSTALL_TIMEOUT
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise InstallError(
            f'Install of {spec!r} timed out after {_INSTALL_TIMEOUT}s'
        ) from exc

    if proc.returncode != 0:
        raise InstallError(
            f'uv pip install {spec!r} failed '
            f'(exit {proc.returncode}): {stderr.decode()}'
        )
    LOGGER.info('Installed %r: %s', spec, stdout.decode().strip())
    return reload_plugins()


async def uninstall_package(name: str) -> LoadResult:
    """Uninstall a plugin package at runtime."""
    if not _INSTALL_ENABLED:
        raise InstallError('Runtime plugin installation is disabled')
    name = _validate_name(name)
    proc = await asyncio.create_subprocess_exec(
        'uv',
        'pip',
        'uninstall',
        '--yes',
        name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_INSTALL_TIMEOUT
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise InstallError(f'Uninstall of {name!r} timed out') from exc

    if proc.returncode != 0:
        raise InstallError(
            f'uv pip uninstall {name!r} failed: {stderr.decode()}'
        )
    LOGGER.info('Uninstalled %r', name)
    return reload_plugins()
