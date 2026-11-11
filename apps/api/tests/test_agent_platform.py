"""Unit tests for the agent platform configuration and marketplaces."""

import json
import pathlib
import typing
import unittest
from unittest import mock

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
            mock.patch.object(
                marketplaces, '_public_readers', return_value=[]
            ),
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

    async def test_a_public_repository_is_read_anonymously(
        self,
    ) -> None:
        handler = mock.AsyncMock(spec=base.DeploymentCapability)
        handler.list_refs.side_effect = RuntimeError('no installation')
        reader = mock.AsyncMock(spec=base.DeploymentCapability)
        reader.list_refs.return_value = [
            base.Ref(name='main', kind='default', sha=SHA, is_default=True)
        ]
        reader.get_file.return_value = '{}'
        public = 'https://github.com/anthropics/plugins'
        with (
            mock.patch.object(
                assignments,
                'org_integrations',
                return_value={'i1': {'slug': 'gh', 'plugin': 'github'}},
            ),
            mock.patch.object(marketplaces, '_handler', return_value=handler),
            mock.patch.object(
                marketplaces,
                '_public_readers',
                side_effect=lambda _db, url: (
                    [reader] if url == public else []
                ),
            ),
        ):
            head = await marketplaces.fetch(mock.Mock(), 'acme', public)
            self.assertEqual(head, marketplaces.Head('main', SHA, '{}'))
            reader.get_file.assert_awaited_once_with(
                None, {}, marketplaces.MARKETPLACE_FILE, SHA
            )
            # A URL that no plugin reads anonymously.
            with self.assertRaisesRegex(
                marketplaces.SyncError, '^gh: no installation$'
            ):
                await marketplaces.fetch(
                    mock.Mock(), 'acme', 'https://ghe.example.com/a/b'
                )

    async def test_public_readers_come_from_enabled_plugins(self) -> None:
        reader = mock.Mock()

        class Deployment(base.DeploymentCapability):  # type: ignore[misc]
            @classmethod
            def public_reader(cls, url: str) -> typing.Any:
                return reader if url == 'https://h/a/b' else None

        class Broken(base.DeploymentCapability):  # type: ignore[misc]
            @classmethod
            def public_reader(cls, url: str) -> typing.Any:
                raise RuntimeError('broken')

        def entry(slug: str, handler: type | None) -> mock.Mock:
            capability = (
                None if handler is None else mock.Mock(handler=handler)
            )
            return mock.Mock(
                **{
                    'manifest.slug': slug,
                    'manifest.get_capability.return_value': capability,
                }
            )

        entries = [
            entry('none', None),
            entry('broken', Broken),
            entry('enabled', Deployment),
            entry('disabled', Deployment),
        ]
        from imbi.api.plugins import lifecycle

        with (
            mock.patch.object(
                marketplaces.plugin_registry,
                'list_plugins',
                return_value=entries,
            ),
            mock.patch.object(
                lifecycle,
                'is_plugin_enabled',
                side_effect=lambda _db, slug: slug != 'disabled',
            ),
        ):
            db = mock.Mock()
            self.assertEqual(
                await marketplaces._public_readers(db, 'https://h/a/b'),
                [reader],
            )
            with self.assertLogs(marketplaces.LOGGER, 'INFO') as logs:
                self.assertEqual(
                    await marketplaces._public_readers(
                        db, 'https://u:secret@x/y?token=t#f'
                    ),
                    [],
                )
            self.assertIn('https://x/y:', logs.output[0])
            self.assertNotIn('secret', '\n'.join(logs.output))
            self.assertNotIn('token', '\n'.join(logs.output))

    async def test_no_integration(self) -> None:
        with (
            mock.patch.object(
                assignments, 'org_integrations', return_value={}
            ),
            mock.patch.object(
                marketplaces, '_public_readers', return_value=[]
            ),
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
        self.assertEqual(
            merged.secrets,
            [platform.SecretReference(reference='secret://ci/token')],
        )
        self.assertEqual(
            platform.merge(
                config, models.AgentSettings(permission_mode='plan')
            ).permission_mode,
            'plan',
        )

    def test_merge_uses_the_agent_model_key(self) -> None:
        config = platform.AgentPlatformConfig(
            model_upstream=platform.ModelUpstream(
                kind='litellm',
                base_url='https://llm.example.com',
                key_ref='secret://anthropic/org#api-key',
            )
        )
        merged = platform.merge(config, models.AgentSettings())
        self.assertEqual(
            merged.model_upstream.key_ref, 'secret://anthropic/org#api-key'
        )
        merged = platform.merge(
            config,
            models.AgentSettings(
                model_key_ref='secret://anthropic/triage#api-key'
            ),
        )
        self.assertEqual(
            merged.model_upstream.key_ref,
            'secret://anthropic/triage#api-key',
        )
        # Only the key changes; the upstream stays the organization's.
        self.assertEqual(merged.model_upstream.kind, 'litellm')
        self.assertEqual(
            str(merged.model_upstream.base_url), 'https://llm.example.com/'
        )
        # The organization's configuration is not changed.
        self.assertEqual(
            config.model_upstream.key_ref, 'secret://anthropic/org#api-key'
        )


HOOKS = {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'audit'}]}]}


class ClaudeSettingsTests(unittest.TestCase):
    def test_refuses_keys_not_on_the_allowlist(self) -> None:
        for document in (
            {'env': {'NODE_OPTIONS': '-r x'}},
            {'permissions': {'defaultMode': 'bypassPermissions'}},
            {'disableAllHooks': True},
            {'hooks': {'PreToolUse': [{'hooks': [{'command': 'x', 'y': 1}]}]}},
            {'hooks': {'NotAnEvent': []}},
            {'permissions': {'allow': ['Bash(']}},
            {'hooks': {'Stop': [{'hooks': [{'command': 'x' * 4097}]}]}},
            {'permissions': {'allow': ['Read'] * 20_000}},
        ):
            with (
                self.subTest(document=str(document)[:60]),
                self.assertRaises(ValueError),
            ):
                models.ClaudeSettings.model_validate(document)

    def test_normalizes_rules_and_leaves_out_unset_keys(self) -> None:
        settings = models.ClaudeSettings.model_validate(
            {'permissions': {'deny': ['  Bash(git push *) ']}}
        )
        self.assertEqual(
            settings.model_dump(mode='json'),
            {'permissions': {'deny': ['Bash(git push *)']}},
        )

    def test_older_hooks_become_enforced_settings(self) -> None:
        config = platform.AgentPlatformConfig.model_validate({'hooks': HOOKS})
        self.assertEqual(
            config.claude_settings.model_dump(mode='json'), {'hooks': HOOKS}
        )
        self.assertEqual(config.enforced, ['hooks'])
        config = platform.AgentPlatformConfig.model_validate({'hooks': {}})
        self.assertEqual(config.enforced, [])

    def test_enforced_paths_refuse_the_agent(self) -> None:
        config = platform.AgentPlatformConfig(enforced=['permissions.deny'])
        settings = models.AgentSettings(
            claude_settings=models.ClaudeSettings.model_validate(
                {'permissions': {'deny': [], 'allow': ['Bash(make *)']}}
            )
        )
        self.assertEqual(
            platform.widenings(config, settings),
            ["the organization enforces claude_settings 'permissions.deny'"],
        )

    def test_agent_hooks_need_the_org_opt_in(self) -> None:
        settings = models.AgentSettings(
            claude_settings=models.ClaudeSettings.model_validate(
                {'hooks': HOOKS}
            )
        )
        config = platform.AgentPlatformConfig()
        self.assertEqual(
            platform.widenings(config, settings),
            ['the organization does not allow agent claude_settings hooks'],
        )
        merged = platform.merge(config, settings)
        self.assertNotIn('hooks', merged.claude_settings)
        self.assertEqual(merged.claude_settings_dropped, ['hooks'])
        config = platform.AgentPlatformConfig(allow_agent_hooks=True)
        self.assertEqual(platform.widenings(config, settings), [])
        self.assertEqual(
            platform.merge(config, settings).claude_settings, {'hooks': HOOKS}
        )

    def test_merge_replaces_each_path_the_org_does_not_enforce(self) -> None:
        config = platform.AgentPlatformConfig(
            claude_settings=models.ClaudeSettings.model_validate(
                {
                    'permissions': {'deny': ['Bash(rm *)'], 'ask': ['Edit']},
                    'hooks': HOOKS,
                    'includeCoAuthoredBy': False,
                }
            ),
            enforced=['hooks'],
        )
        settings = models.AgentSettings(
            claude_settings=models.ClaudeSettings.model_validate(
                {
                    'permissions': {'deny': []},
                    'hooks': {},
                    'respectGitignore': False,
                }
            )
        )
        merged = platform.merge(config, settings)
        self.assertEqual(
            merged.claude_settings,
            {
                # A list is replaced, not joined: the agent removed the
                # organization's deny rule.
                'permissions': {'deny': [], 'ask': ['Edit']},
                'hooks': HOOKS,
                'includeCoAuthoredBy': False,
                'respectGitignore': False,
            },
        )
        self.assertEqual(merged.claude_settings_dropped, ['hooks'])
        self.assertEqual(merged.hooks, HOOKS)


class ModelUpstreamTests(unittest.TestCase):
    def test_http_base_url_needs_the_flag(self) -> None:
        def insecure(**data: typing.Any) -> bool:
            return platform.ModelUpstream.model_validate(data).insecure()

        url = 'http://litellm.imbi:4000'
        self.assertTrue(insecure(base_url=url))
        self.assertFalse(insecure(base_url=url, allow_insecure_http=True))
        self.assertFalse(insecure(base_url='https://llm.example.com'))
        self.assertFalse(insecure())


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

    async def test_renders_the_project_slug(self) -> None:
        self.version.system = 'On {{ project_slug }}.'
        self.version.variable_schema = {
            'project_slug': models.PromptVariable(type='str')
        }
        prompt, error = await harness_api._rendered_prompt(
            mock.Mock(),
            {'short_id': 'T-1', 'project_slug': 'billing'},
            self.bundle,
            'acme',
        )
        self.assertIsNone(error)
        assert prompt is not None
        self.assertEqual(prompt.system, 'On billing.')

    async def test_a_render_error_is_returned(self) -> None:
        self.version.system = '{{ missing.attr }}'
        prompt, error = await harness_api._rendered_prompt(
            mock.Mock(), {'short_id': 'T-1'}, self.bundle, 'acme'
        )
        self.assertIsNone(prompt)
        self.assertTrue(error)
