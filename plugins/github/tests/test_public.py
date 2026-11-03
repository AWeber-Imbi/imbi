"""Tests for the credential-free reader of public repositories."""

import unittest

import respx

from imbi.plugins.github import deployment, public

SHA = 'a' * 40
API = 'https://api.github.com/repos/anthropics/plugins'


class PublicRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def test_public_reader_is_for_github_com_only(self) -> None:
        reader = deployment.GitHubDeployment.public_reader(
            'https://github.com/anthropics/plugins.git'
        )
        assert isinstance(reader, public.PublicRepository)
        self.assertEqual(reader.base, API)
        for url in (
            'https://ghe.example.com/a/b',
            'https://aweber.ghe.com/a/b',
            'https://github.com/orgs',
        ):
            self.assertIsNone(deployment.GitHubDeployment.public_reader(url))

    @respx.mock
    async def test_reads_without_credentials(self) -> None:
        respx.get(API).respond(json={'default_branch': 'main'})
        commit = respx.get(f'{API}/commits/main').respond(json={'sha': SHA})
        respx.get(
            f'{API}/contents/.claude-plugin/marketplace.json',
            params={'ref': SHA},
        ).respond(text='{}')
        respx.get(f'{API}/contents/missing.json', params={'ref': SHA}).respond(
            404
        )
        reader = public.PublicRepository('anthropics', 'plugins')

        refs = await reader.list_refs(None, {}, kind='default')
        self.assertEqual(
            [(r.name, r.kind, r.sha, r.is_default) for r in refs],
            [('main', 'default', SHA, True)],
        )
        self.assertNotIn('authorization', commit.calls.last.request.headers)
        self.assertEqual(
            await reader.get_file(
                None, {}, '.claude-plugin/marketplace.json', SHA
            ),
            '{}',
        )
        self.assertIsNone(await reader.get_file(None, {}, 'missing.json', SHA))
