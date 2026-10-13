"""Live checks of the ``github_app`` provider (plan section 10, P4).

Skipped unless these environment variables are set:

- ``IMBI_LIVE_GITHUB_APP_ID``: the App id of a test App
- ``IMBI_LIVE_GITHUB_INSTALLATION_ID``: its installation id
- ``IMBI_LIVE_GITHUB_PRIVATE_KEY_FILE``: the path of its private key (PEM)
- ``IMBI_LIVE_GITHUB_REPOSITORY``: a sandbox repository, ``owner/name``
- ``IMBI_LIVE_GITHUB_HOST``: optional, ``github.com`` by default. A GHES
  host must also be in ``IMBI_SECRETS_GITHUB_GHES_HOSTS``.

The App needs ``contents``, ``pull_requests``, and ``issues`` write on
the sandbox repository. The test pushes one branch and deletes it.
"""

import base64
import os
import pathlib
import subprocess
import tempfile
import unittest
import uuid
from unittest import mock

import httpx

from imbi.api.secret_broker import github_app, providers

ENV = {
    name: os.environ.get(f'IMBI_LIVE_GITHUB_{name}', '')
    for name in (
        'APP_ID',
        'INSTALLATION_ID',
        'PRIVATE_KEY_FILE',
        'REPOSITORY',
        'HOST',
    )
}


@unittest.skipUnless(
    all(ENV[name] for name in ENV if name != 'HOST'),
    'Set the IMBI_LIVE_GITHUB_* variables to run the live checks',
)
class GitHubAppLiveTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.app = github_app.GitHubApp()
        self.config = self.app.validate_config(
            {'host': ENV['HOST'] or 'github.com'}
        )
        self.locator = self.app.validate_locator(
            {
                'app_id': ENV['APP_ID'],
                'installation_id': ENV['INSTALLATION_ID'],
                'private_key': 'secret://live/github/app_key',
            },
            'dynamic',
        )
        key = pathlib.Path(ENV['PRIVATE_KEY_FILE']).read_text()
        for name, value in (
            ('private_key', mock.AsyncMock(return_value=key)),
            (
                'project_repositories',
                mock.AsyncMock(return_value=[ENV['REPOSITORY']]),
            ),
        ):
            patcher = mock.patch.object(github_app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.workdir = pathlib.Path(tempfile.mkdtemp())
        self.leases: dict[str, str] = {}
        self.url = f'https://{self.config["host"]}/{ENV["REPOSITORY"]}.git'

    async def _token(self, purpose: str) -> str:
        material = await self.app.resolve(
            self.config,
            self.locator,
            None,
            providers.ResolveContext(
                organization_id='live',
                task_id=uuid.uuid4(),
                project_id='live',
                purpose=purpose,
                ttl_seconds=600,
                credential_class='dynamic',
            ),
        )
        assert material.lease_id is not None
        self.leases[material.value.decode()] = material.lease_id
        self.addAsyncCleanup(self.app.revoke, self.config, material.lease_id)
        return material.value.decode()

    def _git(self, token: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run git with the token in a header, never in a URL or log."""
        basic = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
        return subprocess.run(
            [
                'git',
                '-c',
                f'http.extraHeader=Authorization: Basic {basic}',
                *args,
            ],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
        )

    async def test_checkout_write_and_revoke(self) -> None:
        read = await self._token('workspace_checkout')
        clone = self._git(read, 'clone', '--depth', '1', self.url, 'repo')
        self.assertEqual(clone.returncode, 0, 'clone failed')
        self.workdir = self.workdir / 'repo'
        branch = f'imbi-live-{uuid.uuid4().hex[:8]}'
        self._git(read, 'checkout', '-b', branch)
        self._git(
            read,
            '-c',
            'user.name=imbi-live',
            '-c',
            'user.email=imbi-live@example.com',
            'commit',
            '--allow-empty',
            '-m',
            'imbi live check',
        )
        push = self._git(read, 'push', 'origin', branch)
        self.assertNotEqual(push.returncode, 0, 'a read token pushed')

        write = await self._token('github_write')
        push = self._git(write, 'push', 'origin', branch)
        self.assertEqual(push.returncode, 0, 'a write token did not push')
        delete = self._git(write, 'push', 'origin', '--delete', branch)
        self.assertEqual(delete.returncode, 0, 'branch not deleted')

        await self.app.revoke(self.config, self.leases[write])
        async with httpx.AsyncClient(
            base_url=github_app._api_base(self.config['host']),  # pyright: ignore[reportPrivateUsage]
            headers={'Authorization': f'Bearer {write}'},
        ) as client:
            response = await client.get('/installation/repositories')
        self.assertEqual(response.status_code, 401)
