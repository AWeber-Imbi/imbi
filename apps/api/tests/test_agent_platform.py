"""Unit tests for the agent platform configuration and marketplaces."""

import json
import pathlib
import unittest
from unittest import mock

import respx

from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import marketplaces, platform
from imbi.api.plugins import assignments
from imbi.common import models
from imbi.common.plugins import base
from imbi.common.prompts import pool
from imbi.common.prompts import resolve as prompt_resolve

#: ``.claude-plugin/marketplace.json`` of github.com/anthropics/claude-code
#: at b0b7bed9820350bb0942e32c7f00752a99ea3555.
FIXTURE = (
    pathlib.Path(__file__).parent
    / 'fixtures'
    / 'marketplaces'
    / 'claude-code.json'
)

SHA = 'a' * 40


def _marketplace(**plugins: str | None) -> dict[str, object]:
    return {
        'slug': 'tools',
        'url': 'https://github.com/acme/tools',
        'head_sha': SHA,
        'plugins': [
            {'name': name, 'path': path} for name, path in plugins.items()
        ],
    }


class ParseTests(unittest.TestCase):
    def test_real_marketplace(self) -> None:
        catalog = marketplaces.parse(FIXTURE.read_text())
        self.assertEqual(catalog.name, 'claude-code-plugins')
        self.assertEqual(len(catalog.plugins), 13)
        by_name = {p.name: p for p in catalog.plugins}
        self.assertEqual(by_name['code-review'].path, 'plugins/code-review')
        self.assertTrue(by_name['code-review'].description)
        self.assertTrue(all(p.path for p in catalog.plugins))

    def test_sources(self) -> None:
        catalog = marketplaces.parse(
            json.dumps(
                {
                    'name': 'acme',
                    'owner': {'name': 'Acme'},
                    'metadata': {
                        'pluginRoot': './plugins',
                        'description': 'Tools',
                    },
                    'plugins': [
                        {'name': 'bare', 'source': 'bare'},
                        {
                            'name': 'root',
                            'source': '.',
                            'mcpServers': {'grafana': {}, 'alerts': {}},
                        },
                        {'name': 'escape', 'source': './../x'},
                        {'name': 'nested', 'source': 'a/b'},
                        {
                            'name': 'remote',
                            'source': {'source': 'github', 'repo': 'a/b'},
                        },
                        {
                            'name': 'url',
                            'source': {
                                'source': 'url',
                                'url': 'https://ghe.example.com/a/c.git',
                            },
                        },
                        {
                            'name': 'insecure',
                            'source': {'source': 'url', 'url': 'git://x/y'},
                        },
                        {
                            'name': 'npm',
                            'source': {'source': 'npm', 'package': 'x'},
                        },
                        {'name': 'bad name', 'source': './x'},
                        {'name': 'nosource'},
                        {'name': 'bare', 'source': './dup'},
                        'junk',
                    ],
                }
            )
        )
        self.assertEqual(catalog.description, 'Tools')
        paths = {p.name: p.path for p in catalog.plugins}
        self.assertEqual(
            paths,
            {
                'bare': 'plugins/bare',
                'root': '.',
                'escape': None,
                'nested': None,
                'remote': None,
                'url': None,
                'insecure': None,
                'npm': None,
            },
        )
        self.assertEqual(
            {
                p.name: p.repository_url
                for p in catalog.plugins
                if p.repository_url
            },
            {
                'remote': 'https://github.com/a/b.git',
                'url': 'https://ghe.example.com/a/c.git',
            },
        )
        self.assertEqual(
            {p.name: p.mcp_servers for p in catalog.plugins if p.mcp_servers},
            {'root': ['alerts', 'grafana']},
        )

    def test_invalid_documents(self) -> None:
        for text in (
            'not json',
            '[]',
            '{"plugins": []}',
            '{"name": "x"}',
            '{"name": "a b", "plugins": []}',
        ):
            with self.subTest(text=text):
                with self.assertRaises(marketplaces.SyncError):
                    marketplaces.parse(text)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_the_file_at_the_default_head(self) -> None:
        handler = mock.AsyncMock(spec=base.DeploymentCapability)
        handler.list_refs.return_value = [
            base.Ref(name='main', kind='default', sha=SHA, is_default=True)
        ]
        handler.get_file.return_value = '{}'
        integration = {
            'slug': 'github',
            'plugin': 'github',
            'options': {'flavor': 'github'},
            'encrypted_credentials': {},
        }
        with (
            mock.patch.object(
                assignments,
                'org_integrations',
                return_value={'i1': integration},
            ),
            mock.patch.object(marketplaces, '_handler', return_value=handler),
        ):
            head = await marketplaces.fetch(
                mock.Mock(), 'acme', 'https://github.com/acme/tools'
            )
        self.assertEqual(head, marketplaces.Head('main', SHA, '{}'))
        ctx = handler.get_file.call_args.args[0]
        self.assertEqual(
            ctx.project_links,
            {'github-repository': 'https://github.com/acme/tools'},
        )
        self.assertEqual(
            handler.get_file.call_args.args[2:],
            (marketplaces.MARKETPLACE_FILE, SHA),
        )

    async def test_a_missing_file_tries_the_next_integration(self) -> None:
        handler = mock.AsyncMock(spec=base.DeploymentCapability)
        handler.list_refs.return_value = [
            base.Ref(name='main', kind='default', sha=SHA, is_default=True)
        ]
        # The first integration cannot see the file; the second can.
        handler.get_file.side_effect = [None, '{}']
        integrations = {
            f'i{n}': {'slug': f'gh{n}', 'plugin': 'github'} for n in (1, 2)
        }
        with (
            mock.patch.object(
                assignments, 'org_integrations', return_value=integrations
            ),
            mock.patch.object(marketplaces, '_handler', return_value=handler),
        ):
            head = await marketplaces.fetch(
                mock.Mock(), 'acme', 'https://github.com/acme/tools'
            )
            self.assertEqual(head.text, '{}')
            handler.get_file.side_effect = [None, None]
            with self.assertRaisesRegex(
                marketplaces.SyncError, 'gh1: .*not found; gh2: '
            ):
                await marketplaces.fetch(
                    mock.Mock(), 'acme', 'https://github.com/acme/tools'
                )

    async def test_resolves_an_external_plugin_commit(self) -> None:
        handler = mock.AsyncMock(spec=base.DeploymentCapability)
        handler.list_refs.return_value = [
            base.Ref(name='main', kind='default', sha=SHA, is_default=True)
        ]
        handler.resolve_committish.return_value = mock.Mock(sha='b' * 40)

        def plugin(**source: str) -> marketplaces.CatalogPlugin:
            return marketplaces.CatalogPlugin(
                name='x',
                source={'source': 'url', **source},
                repository_url='https://ghe.example.com/a/x.git',
            )

        with (
            mock.patch.object(
                assignments,
                'org_integrations',
                return_value={'i1': {'slug': 'gh', 'plugin': 'github'}},
            ),
            mock.patch.object(marketplaces, '_handler', return_value=handler),
        ):
            # A sha in the source is checked in the repository.
            handler.resolve_committish.return_value = mock.Mock(sha='c' * 40)
            self.assertEqual(
                await marketplaces.resolve_commit(
                    mock.Mock(), 'acme', plugin(sha='c' * 40, ref='v1')
                ),
                'c' * 40,
            )
            self.assertEqual(
                handler.resolve_committish.call_args.args[2], 'c' * 40
            )
            handler.list_refs.assert_not_called()
            handler.resolve_committish.return_value = mock.Mock(sha='d' * 40)
            with self.assertRaises(marketplaces.SyncError):
                await marketplaces.resolve_commit(
                    mock.Mock(), 'acme', plugin(sha='c' * 40)
                )
            handler.resolve_committish.return_value = mock.Mock(sha='b' * 40)
            # An invalid sha or ref is refused, never replaced.
            for source in ({'sha': 'main', 'ref': 'v1'}, {'ref': ''}):
                with self.assertRaises(marketplaces.SyncError):
                    await marketplaces.resolve_commit(
                        mock.Mock(), 'acme', plugin(**source)
                    )
            self.assertEqual(
                await marketplaces.resolve_commit(
                    mock.Mock(), 'acme', plugin(ref='v1')
                ),
                'b' * 40,
            )
            self.assertEqual(
                handler.resolve_committish.call_args.args[2], 'v1'
            )
            self.assertEqual(
                await marketplaces.resolve_commit(
                    mock.Mock(), 'acme', plugin()
                ),
                SHA,
            )
            ctx = handler.list_refs.call_args.args[0]
            self.assertEqual(
                ctx.project_links,
                {'github-repository': 'https://ghe.example.com/a/x.git'},
            )

    async def test_sync_resolves_external_plugins(self) -> None:
        document = json.dumps(
            {
                'name': 'acme',
                'plugins': [
                    {'name': 'local', 'source': './local'},
                    {
                        'name': 'ok',
                        'source': {'source': 'url', 'url': 'https://h/a.git'},
                    },
                    {
                        'name': 'gone',
                        'source': {'source': 'url', 'url': 'https://h/b.git'},
                    },
                    {
                        'name': 'elsewhere',
                        'source': {'source': 'url', 'url': 'https://x/c.git'},
                    },
                    {
                        'name': 'hub',
                        'source': {'source': 'github', 'repo': 'a/d'},
                    },
                    {
                        'name': 'broken',
                        'source': {'source': 'url', 'url': 'https://[x/e.git'},
                    },
                ],
            }
        )

        async def resolve(
            _db: object, _org: str, plugin: marketplaces.CatalogPlugin
        ) -> str:
            if plugin.name == 'gone':
                raise marketplaces.SyncError('not found')
            return 'b' * 40

        store = mock.AsyncMock()
        with (
            mock.patch.object(
                marketplaces,
                'fetch',
                return_value=marketplaces.Head('main', SHA, document),
            ),
            mock.patch.object(
                marketplaces, 'resolve_commit', side_effect=resolve
            ),
        ):
            await marketplaces.sync(
                mock.Mock(),
                store,
                'acme',
                {'id': 'm1', 'slug': 'm', 'url': 'https://h/market'},
            )
        changes = store.set_marketplace_sync.call_args.args[1]
        self.assertEqual(
            {p['name']: p['repository_sha'] for p in changes['plugins']},
            {
                'local': None,
                'ok': 'b' * 40,
                'gone': None,
                'elsewhere': None,
                'hub': None,
                'broken': None,
            },
        )
        # A plugin on another host, github.com too, is not loadable.
        for plugin in changes['plugins'][3:]:
            self.assertIsNone(plugin['repository_url'])
        self.assertIsNone(changes['sync_error'])

    @respx.mock
    async def test_a_public_github_repository_is_read_anonymously(
        self,
    ) -> None:
        handler = mock.AsyncMock(spec=base.DeploymentCapability)
        handler.list_refs.side_effect = RuntimeError('no installation')
        api = 'https://api.github.com/repos/anthropics/plugins'
        respx.get(api).respond(json={'default_branch': 'main'})
        respx.get(f'{api}/commits/main').respond(json={'sha': SHA})
        respx.get(
            f'{api}/contents/.claude-plugin/marketplace.json',
            params={'ref': SHA},
        ).respond(text='{}')
        with (
            mock.patch.object(
                assignments,
                'org_integrations',
                return_value={'i1': {'slug': 'gh', 'plugin': 'github'}},
            ),
            mock.patch.object(marketplaces, '_handler', return_value=handler),
        ):
            head = await marketplaces.fetch(
                mock.Mock(), 'acme', 'https://github.com/anthropics/plugins'
            )
            self.assertEqual(head, marketplaces.Head('main', SHA, '{}'))
            # Another host is never read anonymously.
            with self.assertRaisesRegex(
                marketplaces.SyncError, '^gh: no installation$'
            ):
                await marketplaces.fetch(
                    mock.Mock(), 'acme', 'https://ghe.example.com/a/b'
                )

    async def test_no_integration(self) -> None:
        with mock.patch.object(
            assignments, 'org_integrations', return_value={}
        ):
            with self.assertRaises(marketplaces.SyncError):
                await marketplaces.fetch(mock.Mock(), 'acme', 'https://x/y')


class NarrowingTests(unittest.TestCase):
    def test_widenings(self) -> None:
        config = platform.AgentPlatformConfig(
            permission_mode='default',
            sandbox=models.AgentSandbox(
                enabled=True, allow_unsandboxed_commands=False
            ),
            allowed_marketplaces=['tools'],
        )
        self.assertEqual(
            platform.widenings(config, models.AgentSettings()), []
        )
        self.assertEqual(
            platform.widenings(
                config, models.AgentSettings(permission_mode='plan')
            ),
            [],
        )
        settings = models.AgentSettings(
            permission_mode='bypassPermissions',
            sandbox=models.AgentSandbox(enabled=False),
            plugins=[models.AgentPlugin(marketplace='other', plugin='x')],
        )
        self.assertEqual(len(platform.widenings(config, settings)), 4)

    def test_merge_takes_the_stricter_value(self) -> None:
        default = models.AgentPlugin(
            marketplace='tools', plugin='lint', sha=SHA
        )
        config = platform.AgentPlatformConfig(
            permission_mode='acceptEdits',
            allowed_marketplaces=['tools'],
            default_plugins=[default],
            denied_tools=['WebFetch'],
            approval_tools=['Bash'],
        )
        settings = models.AgentSettings(
            # Wider than the organization: an older configuration
            # allowed it. The merge still takes the stricter value.
            permission_mode='bypassPermissions',
            sandbox=models.AgentSandbox(enabled=True),
            plugins=[
                models.AgentPlugin(marketplace='tools', plugin='lint'),
                models.AgentPlugin(marketplace='tools', plugin='fmt'),
                models.AgentPlugin(marketplace='gone', plugin='x'),
            ],
            denied_tools=['Edit'],
            approval_tools=['Write'],
            secrets=['secret://ci/token'],
        )
        merged = platform.merge(config, settings)
        self.assertEqual(merged.permission_mode, 'acceptEdits')
        self.assertTrue(merged.sandbox.enabled)
        self.assertEqual(
            [(p.plugin, p.sha) for p in merged.plugins],
            [('lint', SHA), ('fmt', None)],
        )
        self.assertEqual(merged.denied_tools, ['Edit', 'WebFetch'])
        self.assertEqual(merged.approval_tools, ['Bash', 'Write'])
        self.assertEqual(merged.secrets, ['secret://ci/token'])
        self.assertEqual(
            platform.merge(
                config, models.AgentSettings(permission_mode='plan')
            ).permission_mode,
            'plan',
        )


class PinTests(unittest.TestCase):
    def test_pins_to_the_catalog_head(self) -> None:
        (plugin,) = platform.pin_plugins(
            [models.AgentPlugin(marketplace='tools', plugin='lint')],
            [],
            {'tools': _marketplace(lint='plugins/lint')},
        )
        self.assertEqual(plugin.sha, SHA)
        self.assertEqual(plugin.url, 'https://github.com/acme/tools')
        self.assertEqual(plugin.path, 'plugins/lint')

    def test_keeps_a_pin_with_the_same_sha(self) -> None:
        old = models.AgentPlugin(
            marketplace='tools', plugin='lint', sha='b' * 40, path='old'
        )
        catalog = {'tools': _marketplace(lint='plugins/lint')}
        (kept,) = platform.pin_plugins(
            [
                models.AgentPlugin(
                    marketplace='tools', plugin='lint', sha='b' * 40
                )
            ],
            [old],
            catalog,
        )
        self.assertEqual(kept, old)
        (repinned,) = platform.pin_plugins(
            [models.AgentPlugin(marketplace='tools', plugin='lint')],
            [old],
            catalog,
        )
        self.assertEqual(repinned.sha, SHA)

    def test_pins_an_external_plugin_to_its_repository(self) -> None:
        catalog = _marketplace()
        catalog['plugins'] = [
            {
                'name': 'remote',
                'path': None,
                'repository_url': 'https://github.com/acme/remote.git',
                'repository_sha': 'b' * 40,
            }
        ]
        (plugin,) = platform.pin_plugins(
            [models.AgentPlugin(marketplace='tools', plugin='remote')],
            [],
            {'tools': catalog},
        )
        self.assertEqual(plugin.url, 'https://github.com/acme/remote.git')
        self.assertEqual(plugin.sha, 'b' * 40)
        self.assertEqual(plugin.path, '.')

    def test_refusals(self) -> None:
        catalog = {'tools': _marketplace(lint='plugins/lint', remote=None)}
        for requested in (
            [models.AgentPlugin(marketplace='nope', plugin='lint')],
            [models.AgentPlugin(marketplace='tools', plugin='nope')],
            [models.AgentPlugin(marketplace='tools', plugin='remote')],
            [models.AgentPlugin(marketplace='tools', plugin='lint')] * 2,
        ):
            with self.subTest(requested=requested):
                with self.assertRaises(ValueError):
                    platform.pin_plugins(requested, [], catalog)


class RenderedPromptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        patcher = mock.patch.object(pool, 'in_process', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        prompt = models.Prompt(name='Triage', slug='triage', namespace='ops')
        self.version = models.PromptVersion(
            prompt=prompt,
            prompt_id='p1',
            n=7,
            system='You are {{ agent }} in {{ organization }}.',
            variable_schema={
                'agent': models.PromptVariable(type='str', required=True),
                'organization': models.PromptVariable(
                    type='str', required=True
                ),
            },
            model='sonnet',
            content_sha256='',
            created_by='x',
        )
        for name, value in (
            ('fetch_prompt', (prompt, 7)),
            ('fetch_version', self.version),
        ):
            patcher = mock.patch.object(
                prompt_resolve, name, return_value=value
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.bundle = harness_api.IdentityBundle(
            agent_id='a1',
            agent_slug='triage',
            agent_version=3,
            snapshot={},
            prompt_ref='ops/triage@stable',
            prompt_version=7,
        )

    async def test_renders_the_pinned_version(self) -> None:
        prompt, error = await harness_api._rendered_prompt(
            mock.Mock(), {'short_id': 'T-1'}, self.bundle, 'acme'
        )
        self.assertIsNone(error)
        assert prompt is not None
        self.assertEqual(prompt.ref, 'ops/triage@7')
        self.assertEqual(prompt.system, 'You are triage in acme.')
        self.assertEqual(prompt.model, 'sonnet')

    async def test_a_render_error_is_returned(self) -> None:
        self.version.system = '{{ missing.attr }}'
        prompt, error = await harness_api._rendered_prompt(
            mock.Mock(), {'short_id': 'T-1'}, self.bundle, 'acme'
        )
        self.assertIsNone(prompt)
        self.assertTrue(error)
