"""Runtime plugin installation via uv pip."""

import asyncio
import logging
import os

from imbi_common.plugins.registry import (
    LoadResult,
    reload_plugins,
)

LOGGER = logging.getLogger(__name__)

_INSTALL_TIMEOUT = int(os.environ.get('IMBI_PLUGINS_INSTALL_TIMEOUT', '120'))
_INSTALL_ENABLED = (
    os.environ.get('IMBI_PLUGINS_INSTALL_ENABLED', 'true').lower() != 'false'
)


class InstallError(Exception):
    """Raised when uv pip install fails."""


async def install_package(name: str, version: str | None = None) -> LoadResult:
    """Install a plugin package at runtime via uv pip."""
    if not _INSTALL_ENABLED:
        raise InstallError(
            'Runtime plugin installation is disabled '
            '(IMBI_PLUGINS_INSTALL_ENABLED=false)'
        )
    spec = f'{name}=={version}' if version else name
    proc = await asyncio.create_subprocess_exec(
        'uv',
        'pip',
        'install',
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
