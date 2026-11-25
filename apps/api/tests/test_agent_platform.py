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
            {
                name: servers
                for name, servers in catalog.entry_servers.items()
                if servers
            },
            {'root': {'grafana': {}, 'alerts': {}}},
        )
        self.assertTrue(all(not p.mcp_servers for p in catalog.plugins))

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


async def _readers(
    handler: object, *integrations: dict[str, typing.Any]
) -> marketplaces.Readers:
    """The readers of an organization whose integrations use
    ``handler``."""
    with (
        mock.patch.object(
            assignments,
            'org_integrations',
            return_value={
                f'i{number}': integration
                for number, integration in enumerate(integrations)
            },
        ),
        mock.patch.object(marketplaces, '_handler', return_value=handler),
        mock.patch.object(marketplaces, '_public_handlers', return_value=[]),
    ):
        return await marketplaces.organization_readers(mock.Mock(), 'acme')


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
        head = await marketplaces.fetch(
            await _readers(handler, integration),
            'https://github.com/acme/tools',
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

    async def test_amissing_file_tries_the_next_integration(self) -> None:
        handler = mock.AsyncMock(spec=base.DeploymentCapability)
        handler.list_refs.return_value = [
            base.Ref(name='main', kind='default', sha=SHA, is_default=True)
        ]
        # The first integration cannot see the file; the second can.
        handler.get_file.side_effect = [None, '{}']
        readers = await _readers(
            handler,
            {'slug': 'gh1', 'plugin': 'github'},
            {'slug': 'gh2', 'plugin': 'github'},
        )
        head = await marketplaces.fetch(
            readers, 'https://github.com/acme/tools'
        )
        self.assertEqual(head.text, '{}')
        handler.get_file.side_effect = [None, None]
        with self.assertRaisesRegex(
            marketplaces.NotFoundError, 'gh1: .*not found; gh2: '
        ):
            await marketplaces.fetch(readers, 'https://github.com/acme/tools')

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

        readers = await _readers(handler, {'slug': 'gh', 'plugin': 'github'})
        # A sha in the source is checked in the repository.
        handler.resolve_committish.return_value = mock.Mock(sha='c' * 40)
        self.assertEqual(
            await marketplaces.resolve_commit(
                readers, plugin(sha='c' * 40, ref='v1')
            ),
            'c' * 40,
        )
        self.assertEqual(
            handler.resolve_committish.call_args.args[2], 'c' * 40
        )
        handler.list_refs.assert_not_called()
        handler.resolve_committish.return_value = mock.Mock(sha='d' * 40)
        with self.assertRaises(marketplaces.SyncError):
            await marketplaces.resolve_commit(readers, plugin(sha='c' * 40))
        handler.resolve_committish.return_value = mock.Mock(sha='b' * 40)
        # An invalid sha or ref is refused, never replaced.
        for source in ({'sha': 'main', 'ref': 'v1'}, {'ref': ''}):
            with self.assertRaises(marketplaces.SyncError):
                await marketplaces.resolve_commit(readers, plugin(**source))
        self.assertEqual(
            await marketplaces.resolve_commit(readers, plugin(ref='v1')),
            'b' * 40,
        )
        self.assertEqual(handler.resolve_committish.call_args.args[2], 'v1')
        self.assertEqual(
            await marketplaces.resolve_commit(readers, plugin()),
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
            _readers: object, plugin: marketplaces.CatalogPlugin
        ) -> str:
            if plugin.name == 'gone':
                raise marketplaces.SyncError('not found')
            return 'b' * 40

        store = mock.AsyncMock()
        with (
            mock.patch.object(
                marketplaces, 'organization_readers', return_value=READERS
            ),
            mock.patch.object(
                marketplaces,
                'fetch',
                return_value=marketplaces.Head('main', SHA, document),
            ),
            mock.patch.object(
                marketplaces, 'resolve_commit', side_effect=resolve
            ),
            mock.patch.object(
                marketplaces, 'file_reader', return_value=missing
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
        readers = await _readers(handler, {'slug': 'gh', 'plugin': 'github'})
        with mock.patch.object(
            marketplaces,
            '_public_readers',
            side_effect=lambda _handlers, url: (
                [reader] if url == public else []
            ),
        ):
            head = await marketplaces.fetch(readers, public)
            self.assertEqual(head, marketplaces.Head('main', SHA, '{}'))
            reader.get_file.assert_awaited_once_with(
                None, {}, marketplaces.MARKETPLACE_FILE, SHA
            )
            # A URL that no plugin reads anonymously.
            with self.assertRaisesRegex(
                marketplaces.SyncError, '^gh: no installation$'
            ):
                await marketplaces.fetch(
                    readers, 'https://ghe.example.com/a/b'
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
            handlers = await marketplaces._public_handlers(mock.Mock())
        self.assertEqual([slug for slug, _ in handlers], ['broken', 'enabled'])
        self.assertEqual(
            marketplaces._public_readers(handlers, 'https://h/a/b'),
            [reader],
        )
        with self.assertLogs(marketplaces.LOGGER, 'INFO') as logs:
            self.assertEqual(
                marketplaces._public_readers(
                    handlers, 'https://u:secret@x/y?token=t#f'
                ),
                [],
            )
            self.assertIn('https://x/y:', logs.output[0])
            self.assertNotIn('secret', '\n'.join(logs.output))
            self.assertNotIn('token', '\n'.join(logs.output))

    async def test_no_integration(self) -> None:
        with self.assertRaisesRegex(
            marketplaces.SyncError, 'has no integration'
        ):
            await marketplaces.fetch(await _readers(None), 'https://x/y')


READERS = marketplaces.Readers([], [])


def _reader(files: dict[str, str]) -> marketplaces.FileReader:
    async def read(path: str) -> str | None:
        return files.get(path)

    return read


async def missing(_path: str) -> str | None:
    return None


def _entry(servers: object) -> marketplaces.EntryServers:
    async def entry() -> object:
        return servers

    return entry


def _names(servers: list[models.CatalogServer]) -> list[str]:
    return [server.name for server in servers]


HTTP = {
    'type': 'http',
    'url': 'https://mcp.example.com/mcp',
    'headers': {
        'Authorization': 'Bearer ${TOKEN}',
        'X-Org': '${ORG:-acme}/${TOKEN}',
        'X-Static': 'literal-secret',
    },
}


class PluginServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_object(self) -> None:
        read = _reader(
            {
                'p/.claude-plugin/plugin.json': json.dumps(
                    {
                        'mcpServers': {
                            'remote': HTTP,
                            'local': {'command': 'npx', 'args': ['x']},
                            'events': {
                                'type': 'sse',
                                'url': 'https://e.example.com/sse',
                            },
                            'junk': 'not an object',
                        }
                    }
                )
            }
        )
        servers = await marketplaces.plugin_servers(
            read, 'p', _entry(None), 'p'
        )
        self.assertEqual(
            [server.model_dump() for server in servers],
            [
                {
                    'name': 'events',
                    'type': 'sse',
                    'url': 'https://e.example.com/sse',
                    'headers': {},
                },
                {'name': 'local', 'type': 'stdio', 'url': None, 'headers': {}},
                {
                    'name': 'remote',
                    'type': 'http',
                    'url': 'https://mcp.example.com/mcp',
                    'headers': {
                        'Authorization': ['TOKEN'],
                        'X-Org': ['ORG', 'TOKEN'],
                        'X-Static': [],
                    },
                },
            ],
        )

    async def test_manifest_paths_and_list(self) -> None:
        read = _reader(
            {
                '.claude-plugin/plugin.json': json.dumps(
                    {
                        'mcpServers': [
                            './config/servers.json',
                            {'inline': {'command': 'x'}},
                            'bare.json',
                        ]
                    }
                ),
                'config/servers.json': json.dumps(
                    {'mcpServers': {'remote': HTTP}}
                ),
                'bare.json': json.dumps({'bare': {'command': 'y'}}),
                '.mcp.json': json.dumps(
                    {
                        'mcpServers': {
                            'remote': {'type': 'sse', 'url': 'https://x'},
                            'extra': {'type': 'http', 'url': 'https://y'},
                        }
                    }
                ),
            }
        )
        servers = await marketplaces.plugin_servers(
            read, '.', _entry(None), 'p'
        )
        self.assertEqual(
            {server.name: server.type for server in servers},
            {
                'bare': 'stdio',
                'extra': 'http',
                'inline': 'stdio',
                'remote': 'http',
            },
        )

    async def test_a_single_path_in_the_manifest(self) -> None:
        read = _reader(
            {
                'p/.claude-plugin/plugin.json': json.dumps(
                    {'mcpServers': './servers.json'}
                ),
                'p/servers.json': json.dumps({'mcpServers': {'file': HTTP}}),
            }
        )
        servers = await marketplaces.plugin_servers(
            read, 'p', _entry(None), 'p'
        )
        self.assertEqual(_names(servers), ['file'])

    async def test_entry_servers_apply_without_a_manifest(self) -> None:
        read = _reader(
            {
                'p/servers.json': json.dumps({'mcpServers': {'file': HTTP}}),
                'p/.mcp.json': json.dumps({'mcpServers': {'mcp': HTTP}}),
            }
        )
        servers = await marketplaces.plugin_servers(
            read, 'p', _entry([{'inline': HTTP}, './servers.json']), 'p'
        )
        self.assertEqual(_names(servers), ['file', 'inline', 'mcp'])

    async def test_a_single_path_in_the_entry(self) -> None:
        read = _reader(
            {'p/servers.json': json.dumps({'mcpServers': {'file': HTTP}})}
        )
        servers = await marketplaces.plugin_servers(
            read, 'p', _entry('./servers.json'), 'p'
        )
        self.assertEqual(_names(servers), ['file'])

    async def test_a_manifest_overrides_entry_servers(self) -> None:
        read = _reader(
            {
                'p/.claude-plugin/plugin.json': '{"name": "p"}',
                'p/.mcp.json': json.dumps({'mcpServers': {'mcp': HTTP}}),
            }
        )
        entry = mock.AsyncMock(return_value={'inline': HTTP})
        servers = await marketplaces.plugin_servers(read, 'p', entry, 'p')
        self.assertEqual(_names(servers), ['mcp'])
        entry.assert_not_awaited()

    async def test_an_invalid_manifest_overrides_entry_servers(self) -> None:
        read = _reader({'p/.claude-plugin/plugin.json': 'not json'})
        servers = await marketplaces.plugin_servers(
            read, 'p', _entry({'inline': HTTP}), 'p'
        )
        self.assertEqual(servers, [])

    async def testmissing_or_invalid_files_add_nothing(self) -> None:
        read = _reader(
            {
                'p/.claude-plugin/plugin.json': json.dumps(
                    {
                        'mcpServers': [
                            'missing.json',
                            'invalid.json',
                            'list.json',
                            'deep.json',
                            7,
                        ]
                    }
                ),
                'p/invalid.json': '{not json',
                'p/list.json': '[]',
                'p/deep.json': '[' * 1_000_000,
                'p/.mcp.json': json.dumps({'mcpServers': {'ok': HTTP}}),
            }
        )
        servers = await marketplaces.plugin_servers(
            read, 'p', _entry(None), 'p'
        )
        self.assertEqual(_names(servers), ['ok'])

    async def test_paths_outside_the_plugin_are_refused(self) -> None:
        outside = json.dumps({'mcpServers': {'outside': HTTP}})
        read = _reader(
            {
                'p/.claude-plugin/plugin.json': json.dumps(
                    {'mcpServers': ['../outside.json', '/etc/servers.json']}
                ),
                'outside.json': outside,
                '/etc/servers.json': outside,
                'p/.mcp.json': json.dumps({'mcpServers': {'ok': HTTP}}),
            }
        )
        with self.assertLogs(marketplaces.LOGGER, 'WARNING') as logs:
            servers = await marketplaces.plugin_servers(
                read, 'p', _entry(None), 'Marketplace m, plugin p'
            )
        self.assertEqual(_names(servers), ['ok'])
        self.assertEqual(len(logs.output), 2)
        self.assertIn('Marketplace m, plugin p', logs.output[0])
        self.assertIn("'../outside.json'", logs.output[0])
        self.assertIn("'/etc/servers.json'", logs.output[1])

    def test_urls_keep_no_credentials(self) -> None:
        servers = marketplaces.servers(
            [
                {
                    'userinfo': {
                        'type': 'http',
                        'url': 'https://user:token@mcp.example.com:8443/mcp',
                    },
                    'query': {
                        'type': 'sse',
                        'url': 'https://mcp.example.com/sse?key=token#part',
                    },
                    'invalid': {'type': 'http', 'url': 'https://[mcp/x'},
                    'missing': {'type': 'http'},
                    'template': {
                        'type': 'http',
                        'url': (
                            '${MCP_URL:-https://user:token'
                            '@mcp.example.com}/mcp'
                        ),
                    },
                    'hostless': {'type': 'http', 'url': 'https://user@/mcp'},
                    'port_only': {'type': 'http', 'url': 'https://:443/mcp'},
                }
            ]
        )
        self.assertEqual(
            {server.name: server.url for server in servers},
            {
                'hostless': None,
                'invalid': None,
                'missing': None,
                'port_only': None,
                'template': None,
                'query': 'https://mcp.example.com/sse',
                'userinfo': 'https://mcp.example.com:8443/mcp',
            },
        )

    def test_header_variables(self) -> None:
        servers = marketplaces.servers(
            [
                {
                    'repeated': {
                        'type': 'http',
                        'headers': {'A': '${A}-${A}', 'B': 7},
                    },
                    'listed': {'type': 'http', 'headers': ['A']},
                }
            ]
        )
        self.assertEqual(
            {server.name: server.headers for server in servers},
            {'listed': {}, 'repeated': {'A': ['A'], 'B': []}},
        )


class FileReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.handler = mock.AsyncMock(spec=base.DeploymentCapability)
        readers = await _readers(
            self.handler,
            {'slug': 'gh1', 'plugin': 'github'},
            {'slug': 'gh2', 'plugin': 'github'},
        )
        self.read = marketplaces.file_reader(readers, 'https://h/a', SHA)

    async def test_falls_through_to_the_next_reader(self) -> None:
        self.handler.get_file.side_effect = [None, '{}']
        self.assertEqual(await self.read('p/.mcp.json'), '{}')
        self.assertEqual(
            self.handler.get_file.call_args.args[2:], ('p/.mcp.json', SHA)
        )

    async def test_not_found_by_every_reader(self) -> None:
        self.handler.get_file.side_effect = [None, None]
        self.assertIsNone(await self.read('p/.mcp.json'))

    async def test_an_error_from_every_reader(self) -> None:
        self.handler.get_file.side_effect = RuntimeError('no access')
        with self.assertRaisesRegex(
            marketplaces.SyncError,
            '^cannot read p/.mcp.json: gh1: no access; gh2: no access$',
        ):
            await self.read('p/.mcp.json')

    async def test_not_found_by_one_reader_and_an_error(self) -> None:
        self.handler.get_file.side_effect = [None, RuntimeError('timeout')]
        self.assertIsNone(await self.read('p/.mcp.json'))


class SyncServerTests(unittest.IsolatedAsyncioTestCase):
    def test_an_external_entry_is_the_first_with_a_source(self) -> None:
        document = {
            'plugins': [
                'not an object',
                {'name': 'x', 'mcpServers': {'no-source': HTTP}},
                {'name': 'y', 'source': '.', 'mcpServers': {'other': HTTP}},
                {'name': 'x', 'source': '.', 'mcpServers': {'first': HTTP}},
                {'name': 'x', 'source': '.', 'mcpServers': {'second': HTTP}},
            ]
        }
        self.assertEqual(
            marketplaces._entry_servers(document, 'x'), {'first': HTTP}
        )
        self.assertIsNone(marketplaces._entry_servers({'plugins': {}}, 'x'))

    async def sync(
        self,
        document: dict[str, typing.Any],
        files: dict[tuple[str, str, str], str],
    ) -> tuple[dict[str, typing.Any], set[str]]:
        """Sync ``document`` and return the changes and the URLs read."""
        urls: set[str] = set()

        def file_reader(
            _readers: object, url: str, ref: str
        ) -> marketplaces.FileReader:
            async def read(path: str) -> str | None:
                urls.add(url)
                return files.get((url, ref, path))

            return read

        async def resolve(
            _readers: object, plugin: marketplaces.CatalogPlugin
        ) -> str:
            if plugin.name == 'unresolved':
                raise marketplaces.SyncError('not found')
            return 'b' * 40

        store = mock.AsyncMock()
        with (
            mock.patch.object(
                marketplaces, 'organization_readers', return_value=READERS
            ),
            mock.patch.object(
                marketplaces,
                'fetch',
                return_value=marketplaces.Head(
                    'main', SHA, json.dumps(document)
                ),
            ),
            mock.patch.object(
                marketplaces, 'resolve_commit', side_effect=resolve
            ),
            mock.patch.object(
                marketplaces, 'file_reader', side_effect=file_reader
            ),
        ):
            await marketplaces.sync(
                mock.Mock(),
                store,
                'acme',
                {'id': 'm1', 'slug': 'm', 'url': 'https://h/market'},
            )
        return store.set_marketplace_sync.call_args.args[1], urls

    async def test_sync_reads_the_servers_of_each_plugin(self) -> None:
        external_url = 'https://h/external'
        document = {
            'name': 'acme',
            'plugins': [
                {
                    'name': 'local',
                    'source': './local',
                    'mcpServers': {'entry': HTTP},
                },
                {
                    'name': 'external',
                    'source': {'source': 'url', 'url': external_url},
                    'mcpServers': {'ignored': HTTP},
                },
                {
                    'name': 'unresolved',
                    'source': {'source': 'url', 'url': 'https://h/gone'},
                },
                {
                    'name': 'elsewhere',
                    'source': {'source': 'url', 'url': 'https://x/other'},
                },
                {'name': 'npm', 'source': {'source': 'npm', 'package': 'x'}},
            ],
        }
        external = (external_url, 'b' * 40)
        files = {
            ('https://h/market', SHA, 'local/.mcp.json'): json.dumps(
                {'mcpServers': {'local': HTTP}}
            ),
            (*external, '.mcp.json'): json.dumps(
                {'mcpServers': {'external': HTTP}}
            ),
            (*external, marketplaces.MARKETPLACE_FILE): json.dumps(
                {
                    'plugins': [
                        {
                            'name': 'external',
                            'source': '.',
                            'mcpServers': {'own': HTTP},
                        }
                    ]
                }
            ),
        }
        changes, urls = await self.sync(document, files)
        self.assertEqual(
            {
                plugin['name']: [
                    server['name'] for server in plugin['mcp_servers']
                ]
                for plugin in changes['plugins']
            },
            {
                'local': ['entry', 'local'],
                'external': ['external', 'own'],
                'unresolved': [],
                'elsewhere': [],
                'npm': [],
            },
        )
        self.assertEqual(urls, {'https://h/market', external_url})
        stored = json.dumps(changes, default=str)
        self.assertNotIn('Bearer', stored)
        self.assertNotIn('literal-secret', stored)

    async def test_an_external_manifest_overrides_its_entry(self) -> None:
        external = ('https://h/external', 'b' * 40)
        document = {
            'name': 'acme',
            'plugins': [
                {
                    'name': 'external',
                    'source': {'source': 'url', 'url': external[0]},
                }
            ],
        }
        files = {
            (*external, marketplaces.PLUGIN_MANIFEST): '{"name": "external"}',
            (*external, marketplaces.MARKETPLACE_FILE): json.dumps(
                {
                    'plugins': [
                        {
                            'name': 'external',
                            'source': '.',
                            'mcpServers': {'own': HTTP},
                        }
                    ]
                }
            ),
        }
        changes, _ = await self.sync(document, files)
        self.assertEqual(changes['plugins'][0]['mcp_servers'], [])

    async def test_a_read_error_fails_the_sync(self) -> None:
        document = {
            'name': 'acme',
            'plugins': [{'name': 'local', 'source': './local'}],
        }

        async def read(_path: str) -> str | None:
            raise marketplaces.SyncError('cannot read local/x: gh: boom')

        store = mock.AsyncMock()
        with (
            mock.patch.object(
                marketplaces, 'organization_readers', return_value=READERS
            ),
            mock.patch.object(
                marketplaces,
                'fetch',
                return_value=marketplaces.Head(
                    'main', SHA, json.dumps(document)
                ),
            ),
            mock.patch.object(marketplaces, 'file_reader', return_value=read),
        ):
            await marketplaces.sync(
                mock.Mock(),
                store,
                'acme',
                {'id': 'm1', 'slug': 'm', 'url': 'https://h/market'},
            )
        self.assertEqual(
            store.set_marketplace_sync.call_args.args[1],
            {'sync_error': 'cannot read local/x: gh: boom'},
        )


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

    def test_merge_opt_in_builtin_tools(self) -> None:
        settings = models.AgentSettings()
        both = {'builtin.Skill': {}, 'builtin.Agent': {}}
        # Off without the tool map key.
        merged = platform.merge(platform.AgentPlatformConfig(), settings)
        self.assertIsNone(merged.allowed_tools)
        self.assertEqual(merged.builtin_tools, [])
        # On with it, when the organization allows all built-in tools.
        merged = platform.merge(platform.AgentPlatformConfig(), settings, both)
        self.assertEqual(merged.builtin_tools, ['Agent', 'Skill'])
        self.assertEqual(
            platform.merge(
                platform.AgentPlatformConfig(),
                settings,
                {'builtin.Skill': {}, 'imbi.get_me': {}},
            ).builtin_tools,
            ['Skill'],
        )
        # An explicit allowed_tools is the ceiling, not the switch: it
        # keeps only the opt-in tools that the agent turned on, and the
        # agent turns on only those that it names.
        config = platform.AgentPlatformConfig(
            allowed_tools=['Read', 'Skill', 'Task']
        )
        merged = platform.merge(config, settings)
        self.assertEqual(merged.allowed_tools, ['Read'])
        self.assertEqual(merged.builtin_tools, [])
        merged = platform.merge(config, settings, both)
        self.assertEqual(merged.allowed_tools, ['Read', 'Skill', 'Task'])
        self.assertEqual(merged.builtin_tools, ['Agent', 'Skill'])
        merged = platform.merge(config, settings, {'builtin.Skill': {}})
        self.assertEqual(merged.allowed_tools, ['Read', 'Skill'])
        self.assertEqual(merged.builtin_tools, ['Skill'])
        merged = platform.merge(
            platform.AgentPlatformConfig(allowed_tools=['Read']),
            settings,
            both,
        )
        self.assertEqual(merged.builtin_tools, [])
        # A deny rule of the organization or the agent wins, by name or
        # by the earlier name of the tool.
        for config, agent_denied in (
            (platform.AgentPlatformConfig(denied_tools=['Skill']), []),
            (platform.AgentPlatformConfig(), ['Skill']),
        ):
            merged = platform.merge(
                config, models.AgentSettings(denied_tools=agent_denied), both
            )
            self.assertEqual(merged.builtin_tools, ['Agent'])
        merged = platform.merge(
            platform.AgentPlatformConfig(denied_tools=['Task']),
            settings,
            both,
        )
        self.assertEqual(merged.builtin_tools, ['Skill'])

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
            {'permissions': {'allow': ['Read'] * 20_000}},
            # Bytes, not characters: 40,000 characters in 80,000 bytes.
            {'attribution': {'commit': 'é' * 40_000}},
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
        # An older version had no command length limit.
        long = {
            'Stop': [{'hooks': [{'type': 'command', 'command': 'x' * 5000}]}]
        }
        config = platform.AgentPlatformConfig.model_validate({'hooks': long})
        self.assertEqual(config.claude_settings.model_dump()['hooks'], long)

    def test_merge_can_be_larger_than_each_document(self) -> None:
        config = platform.AgentPlatformConfig(
            claude_settings=models.ClaudeSettings.model_validate(
                {'attribution': {'commit': 'x' * 40_000}}
            )
        )
        settings = models.AgentSettings(
            claude_settings=models.ClaudeSettings.model_validate(
                {'permissions': {'allow': [f'Read({"x" * 40_000})']}}
            )
        )
        merged = platform.merge(config, settings).claude_settings
        self.assertEqual(len(merged['attribution']['commit']), 40_000)
        self.assertEqual(len(merged['permissions']['allow']), 1)

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

    def test_merge_gives_a_default_plugin_the_agent_settings(self) -> None:
        off = {'grafana': models.ServerSetting(enabled=False)}
        stale = {'gone': models.ServerSetting(enabled=False)}
        config = platform.AgentPlatformConfig(
            allowed_marketplaces=['tools'],
            default_plugins=[
                models.AgentPlugin(marketplace='tools', plugin='ops', sha=SHA),
                models.AgentPlugin(
                    marketplace='tools', plugin='lint', sha=SHA
                ),
            ],
        )
        settings = models.AgentSettings(
            plugins=[
                models.AgentPlugin(
                    marketplace='tools',
                    plugin='ops',
                    sha='b' * 40,
                    server_settings=off | stale,
                ),
                models.AgentPlugin(
                    marketplace='tools', plugin='fmt', server_settings=off
                ),
            ]
        )
        merged = platform.merge(config, settings)
        self.assertEqual(
            [(p.plugin, p.sha, p.server_settings) for p in merged.plugins],
            [
                ('ops', SHA, off | stale),
                ('lint', SHA, {}),
                ('fmt', None, off),
            ],
        )


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


class PinServerSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog = _marketplace(ops='plugins/ops')
        catalog['plugins'] = [
            {
                'name': 'ops',
                'path': 'plugins/ops',
                'mcp_servers': [
                    {'name': 'grafana', 'type': 'http', 'url': 'https://g'},
                    {'name': 'tempo'},
                ],
            }
        ]
        self.catalog = {'tools': catalog}

    @staticmethod
    def off(*names: str) -> dict[str, models.ServerSetting]:
        return {name: models.ServerSetting(enabled=False) for name in names}

    def test_a_new_pin_saves_the_servers_and_known_settings(self) -> None:
        (plugin,) = platform.pin_plugins(
            [
                models.AgentPlugin(
                    marketplace='tools',
                    plugin='ops',
                    server_settings=self.off('grafana', 'gone'),
                )
            ],
            [],
            self.catalog,
        )
        self.assertEqual(plugin.sha, SHA)
        self.assertEqual(
            plugin.mcp_servers,
            [
                models.CatalogServer(
                    name='grafana', type='http', url='https://g'
                ),
                models.CatalogServer(name='tempo'),
            ],
        )
        self.assertEqual(plugin.server_settings, self.off('grafana'))

    def test_a_kept_pin_takes_the_requested_settings(self) -> None:
        old = models.AgentPlugin(
            marketplace='tools',
            plugin='ops',
            sha='b' * 40,
            mcp_servers=[models.CatalogServer(name='loki')],
            server_settings=self.off('loki'),
        )
        (kept,) = platform.pin_plugins(
            [
                models.AgentPlugin(
                    marketplace='tools',
                    plugin='ops',
                    sha='b' * 40,
                    server_settings=self.off('tempo'),
                )
            ],
            [old],
            self.catalog,
        )
        self.assertEqual(
            kept, old.model_copy(update={'server_settings': self.off('tempo')})
        )

    def test_a_default_plugin_gets_the_default_pin(self) -> None:
        default = models.AgentPlugin(
            marketplace='tools',
            plugin='ops',
            url='https://github.com/acme/tools',
            sha='c' * 40,
            path='plugins/ops',
            mcp_servers=[models.CatalogServer(name='loki')],
        )
        (plugin,) = platform.pin_plugins(
            [
                models.AgentPlugin(
                    marketplace='tools',
                    plugin='ops',
                    server_settings=self.off('loki', 'grafana'),
                )
            ],
            [],
            {},
            [default],
        )
        self.assertEqual(
            plugin,
            default.model_copy(update={'server_settings': self.off('loki')}),
        )

    def test_a_default_pin_with_no_saved_servers_keeps_settings(
        self,
    ) -> None:
        default = models.AgentPlugin(
            marketplace='tools', plugin='ops', url='u', sha='c' * 40
        )
        (plugin,) = platform.pin_plugins(
            [
                models.AgentPlugin(
                    marketplace='tools',
                    plugin='ops',
                    server_settings=self.off('anything'),
                )
            ],
            [],
            {},
            [default],
        )
        self.assertEqual(plugin.sha, 'c' * 40)
        self.assertEqual(plugin.server_settings, self.off('anything'))


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
            mock.Mock(),
            {'short_id': 'T-1', 'projects': []},
            self.bundle,
            'acme',
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
            {
                'short_id': 'T-1',
                'projects': [
                    {'project_id': 'p1', 'project_slug': 'billing'},
                    {'project_id': 'p2', 'project_slug': 'search'},
                ],
            },
            self.bundle,
            'acme',
        )
        self.assertIsNone(error)
        assert prompt is not None
        self.assertEqual(prompt.system, 'On billing,search.')

    async def test_a_render_error_is_returned(self) -> None:
        self.version.system = '{{ missing.attr }}'
        prompt, error = await harness_api._rendered_prompt(
            mock.Mock(),
            {'short_id': 'T-1', 'projects': []},
            self.bundle,
            'acme',
        )
        self.assertIsNone(prompt)
        self.assertTrue(error)
