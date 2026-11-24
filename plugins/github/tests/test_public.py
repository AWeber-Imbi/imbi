"""Tests for the credential-free reader of public repositories."""

import typing
import unittest

import respx

from imbi.plugins.github import deployment, public

SHA = 'a' * 40
API = 'https://api.github.com/repos/anthropics/plugins'
RAW = 'https://raw.githubusercontent.com/anthropics/plugins'


class PublicRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def test_public_reader_is_for_github_com_only(self) -> None:
        reader = deployment.GitHubDeployment.public_reader(
            'https://github.com/anthropics/plugins.git'
        )
        self.assertIsInstance(reader, public.PublicRepository)
        reader = typing.cast(public.PublicRepository, reader)
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
        file = respx.get(
            f'{RAW}/{SHA}/.claude-plugin/marketplace.json'
        ).respond(text='{}')
        respx.get(f'{RAW}/{SHA}/missing.json').respond(404)
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
        self.assertNotIn('authorization', file.calls.last.request.headers)

    @respx.mock
    async def test_get_file_encodes_the_ref(self) -> None:
        route = respx.get(f'{RAW}/release%26candidate/a.json').respond(
            text='{}'
        )
        reader = public.PublicRepository('anthropics', 'plugins')
        self.assertEqual(
            await reader.get_file(None, {}, 'a.json', 'release&candidate'),
            '{}',
        )
        self.assertTrue(route.called)

    @respx.mock
    async def test_get_file_encodes_the_path(self) -> None:
        route = respx.get(f'{RAW}/{SHA}/my%20plugin/.mcp.json').respond(
            text='{}'
        )
        reader = public.PublicRepository('anthropics', 'plugins')
        self.assertEqual(
            await reader.get_file(None, {}, 'my plugin/.mcp.json', SHA), '{}'
        )
        self.assertEqual(
            route.calls.last.request.url.raw_path,
            f'/anthropics/plugins/{SHA}/my%20plugin/.mcp.json'.encode(),
        )


class WebhookSignatureTests(unittest.TestCase):
    def test_signature_is_the_webhook_secret(self) -> None:
        from imbi.plugins.github.plugin import GitHubWebhookActions

        signature = GitHubWebhookActions.signature()
        self.assertEqual(
            (signature.header, signature.prefix, signature.secret),
            ('x-hub-signature-256', 'sha256=', 'webhook'),
        )
